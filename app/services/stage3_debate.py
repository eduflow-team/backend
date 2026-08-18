"""Langflow Stage3 출력을 토론장 발언(turn)으로 정규화하고 사용 점수를 채점한다.

학생이 평가받는 대상은 어느 쪽이 이겼느냐가 아니라,
팩트체커를 판단이 필요한 순간에 썼는지다.
"""

from __future__ import annotations

import json
import re

from app.core.exceptions import Stage3TurnNotFoundError

VERDICT_RANK = {
    "false": 3,
    "unsupported": 2,
    "exaggerated": 1,
    "supported": 0,
}

NEEDS_CHECK = frozenset({"exaggerated", "unsupported", "false"})
PENALIZE_UNNECESSARY_CHECK = True

ROUND_META = [
    ("pro", "pro-1", "1라운드 · 주장"),
    ("con", "con-1", "1라운드 · 반박"),
    ("rebut", "pro-2", "2라운드 · 재반박"),
]


def parse_fact_json(text: str) -> dict | None:
    cleaned = (text or "").strip()
    fence = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, re.DOTALL)
    if fence:
        cleaned = fence.group(1)
    try:
        parsed = json.loads(cleaned)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start != -1 and end > start:
            try:
                parsed = json.loads(cleaned[start : end + 1])
                return parsed if isinstance(parsed, dict) else None
            except json.JSONDecodeError:
                return None
        return None


def tokens(text: str) -> set[str]:
    return set(re.findall(r"[가-힣]{2,}|[A-Za-z0-9%]{2,}", (text or "").lower()))


def overlap_ratio(claim: str, source: str) -> float:
    a, b = tokens(claim), tokens(source)
    if not a or not b:
        return 0.0
    return len(a & b) / len(a)


def parse_speech(text: str) -> tuple[str, list[str]]:
    """주장 요약과 번호 달린 근거를 분리한다."""

    raw = (text or "").strip()
    summary = ""
    match = re.search(r"주장 요약\s*[:：]\s*(.+)", raw)
    if match:
        summary = match.group(1).strip().split("\n")[0].strip()
    if not summary:
        match = re.search(r"최종 입장\s*[:：]\s*(.+)", raw)
        if match:
            summary = match.group(1).strip().split("\n")[0].strip()

    grounds: list[str] = []
    block = re.search(
        r"(?:핵심 근거|보강 근거)\s*[:：]?\s*\n((?:\s*[-•]?\s*\d+[.)]\s*.+\n?)+)",
        raw,
    )
    if block:
        grounds = [
            item.strip()
            for item in re.findall(r"\d+[.)]\s*(.+)", block.group(1))
            if item.strip()
        ]

    if not summary:
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("【") or line.endswith(":") or line.endswith("："):
                continue
            summary = line
            break
    if not summary:
        summary = raw[:220]

    return summary, grounds


def _worst(claims: list[dict]) -> dict | None:
    if not claims:
        return None
    return max(claims, key=lambda item: VERDICT_RANK.get(str(item.get("verdict") or ""), -1))


def _norm_claim(item: object) -> dict | None:
    if not isinstance(item, dict):
        return None
    claim = str(item.get("claim") or "").strip()
    verdict = str(item.get("verdict") or "unsupported").strip().lower()
    if verdict not in VERDICT_RANK:
        verdict = "unsupported"
    reason = str(item.get("reason") or item.get("why") or "").strip()
    if not claim:
        return None
    return {"claim": claim, "verdict": verdict, "reason": reason}


def collect_fact_claims(fact: dict | None) -> list[tuple[str, dict]]:
    if not fact:
        return []
    out: list[tuple[str, dict]] = []
    for item in fact.get("pro_claims_checked") or []:
        claim = _norm_claim(item)
        if claim:
            out.append(("pro", claim))
    for item in fact.get("rebuttal_claims_checked") or []:
        claim = _norm_claim(item)
        if claim:
            out.append(("pro", claim))
    for item in fact.get("con_claims_checked") or []:
        claim = _norm_claim(item)
        if claim:
            out.append(("con", claim))
    return out


def attach_claims(turns: list[dict], fact: dict | None) -> None:
    bags = collect_fact_claims(fact)
    for side, claim in bags:
        candidates = [turn for turn in turns if turn["side"] == side]
        if not candidates:
            continue
        best = max(
            candidates,
            key=lambda turn: overlap_ratio(
                claim["claim"],
                f"{turn['text']} {turn['claim']} {turn.get('raw', '')}",
            ),
        )
        best.setdefault("claims", []).append(claim)

    for turn in turns:
        claims = turn.get("claims") or []
        worst = _worst(claims)
        if worst:
            turn["verdict"] = worst["verdict"]
            turn["why"] = worst["reason"]
            if not turn.get("claim"):
                turn["claim"] = worst["claim"]
        else:
            turn["verdict"] = "supported"
            turn["why"] = "이 발언에서 팩트체커가 따로 문제 삼은 근거는 없습니다."
            turn["claims"] = []


def build_turns(
    rounds: list[dict],
    fact: dict | None,
    *,
    topic: str,
    pro_role: str,
    con_role: str,
    elapsed: float | None = None,
    source: str = "langflow",
    mode: str = "v2",
) -> dict:
    """Langflow 결과 → 학생 UI가 그대로 쓰는 페이로드."""

    by_role = {item.get("role"): item for item in rounds}
    turns: list[dict] = []
    for role, turn_id, label in ROUND_META:
        raw = (by_role.get(role) or {}).get("text") or ""
        if not str(raw).strip():
            continue
        summary, grounds = parse_speech(raw)
        claim = grounds[0] if grounds else summary
        side = "con" if role == "con" else "pro"
        turns.append(
            {
                "id": turn_id,
                "side": side,
                "round": label,
                "text": summary,
                "claim": claim,
                "grounds": grounds,
                "raw": raw,
                "verdict": "supported",
                "why": "",
                "claims": [],
            }
        )

    attach_claims(turns, fact)
    for turn in turns:
        turn.pop("raw", None)

    return {
        "topic": topic,
        "source": source,
        "elapsed": elapsed,
        "mode": mode,
        "pro": {"name": "찬성 측 AI", "role": pro_role},
        "con": {"name": "반대 측 AI", "role": con_role},
        "turns": turns,
        "fact_check": fact or {},
    }


def turn_needs_check(turn: dict) -> bool:
    claims = turn.get("claims") or []
    if claims:
        return any(str(item.get("verdict")) in NEEDS_CHECK for item in claims)
    return str(turn.get("verdict")) in NEEDS_CHECK


def public_turns(
    turns: list[dict],
    checked_ids: set[str],
    *,
    reveal_all: bool = False,
) -> list[dict]:
    """판정은 팩트체크한 발언(또는 최종 제출)에서만 공개한다."""

    visible: list[dict] = []
    for turn in turns:
        item = {
            "id": turn.get("id"),
            "side": turn.get("side"),
            "round": turn.get("round"),
            "text": turn.get("text") or "",
            "claim": turn.get("claim") or "",
            "grounds": list(turn.get("grounds") or []),
        }
        if reveal_all or str(turn.get("id")) in checked_ids:
            item["verdict"] = turn.get("verdict") or "supported"
            item["why"] = turn.get("why") or ""
            item["claims"] = list(turn.get("claims") or [])
        visible.append(item)
    return visible


def resolve_checked_turn_ids(
    turns: list[dict],
    stored_checked: set[str],
    decisions: list | None,
) -> set[str]:
    """제출 시 검증한 발언 id 집합.

    `decisions`가 비어 있으면 팩트체크 API 기록(`stored_checked`)을 사용한다.
    빈 배열 `[]`도 '명시적 결정 없음'으로 취급해 전부 미검증으로 채점하지 않는다.
    """

    if not decisions:
        return set(stored_checked)

    known_ids = {str(turn.get("id")) for turn in turns}
    checked: set[str] = set()
    for item in decisions:
        turn_id = str(getattr(item, "turn_id", "") or "").strip()
        if turn_id not in known_ids:
            raise Stage3TurnNotFoundError()
        if getattr(item, "checked", False):
            checked.add(turn_id)
    return checked


def grade_usage(turns: list[dict], checked_ids: set[str]) -> dict:
    rows: list[dict] = []
    for turn in turns:
        turn_id = str(turn.get("id") or "")
        checked = turn_id in checked_ids
        suspicious = turn_needs_check(turn)
        if suspicious and checked:
            outcome = "caught"
        elif suspicious and not checked:
            outcome = "missed"
        elif not suspicious and checked:
            outcome = "wasted" if PENALIZE_UNNECESSARY_CHECK else "caught"
        else:
            outcome = "passed"
        rows.append(
            {
                "id": turn_id,
                "side": turn.get("side"),
                "round": turn.get("round"),
                "text": turn.get("text") or "",
                "claim": turn.get("claim") or "",
                "verdict": turn.get("verdict") or "supported",
                "why": turn.get("why") or "",
                "checked": checked,
                "suspicious": suspicious,
                "outcome": outcome,
            }
        )

    caught = sum(1 for row in rows if row["outcome"] == "caught")
    passed = sum(1 for row in rows if row["outcome"] == "passed")
    missed = sum(1 for row in rows if row["outcome"] == "missed")
    wasted = sum(1 for row in rows if row["outcome"] == "wasted")
    correct = caught + passed
    score = round((correct / len(rows)) * 100) if rows else 0

    if score >= 90:
        headline = "팩트체커를 정확한 순간에 썼어요"
        advice = "의심할 발언과 넘어가도 될 발언을 거의 정확히 갈랐습니다."
    elif score >= 70:
        headline = "대체로 잘 판단했어요"
        advice = "몇 개만 더 잡아내면 완벽합니다. 아래에서 놓친 발언을 확인해 보세요."
    elif score >= 50:
        headline = "조금 더 의심해 볼까요"
        advice = "숫자가 들어간 주장은 특히 검증할 가치가 큽니다."
    else:
        headline = "검증 기준을 다시 세워 봐요"
        advice = "'구체적인 수치'와 '대부분·모두 같은 표현'이 나오면 팩트체커를 떠올려 보세요."

    if missed == 0 and wasted > 0:
        advice = (
            "허술한 근거는 모두 잡아냈지만, 탄탄한 근거까지 검증했습니다. "
            "검증도 비용이라는 점을 기억하세요."
        )
    elif wasted == 0 and missed > 0:
        advice = (
            "불필요한 검증은 없었지만 놓친 발언이 있습니다. "
            "수치가 나오면 한 번 더 의심해 보세요."
        )

    return {
        "rows": rows,
        "caught": caught,
        "passed": passed,
        "missed": missed,
        "wasted": wasted,
        "score": score,
        "headline": headline,
        "advice": advice,
    }
