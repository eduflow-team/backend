"""Stage 3 학생 근거 설명(why/ground) G-Eval 채점."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.services.stage3_debate import NEEDS_CHECK, turn_needs_check, tokens
from app.services.stage3_sources import find_turn_sources

logger = logging.getLogger(__name__)

_CORRECTION_RUBRIC = """\
평가 기준(stage3_correction):
- why_quality: 학생이 틀린 이유(why_wrong)가 팩트체커 판정·사유와 논리적으로 맞는지
- ground_quality: 학생이 제시한 맞는 근거(correct_ground)가 출처·사실과 연결되는지

평가 단계:
1) highlight가 문제 claim/근거와 관련 있는지
2) why_wrong이 verdict(unsupported/exaggerated/false)와 fact_checker_why를 반영하는지
3) correct_ground가 reference_sources·올바른 반박 방향과 맞는지
4) why_quality, ground_quality 각각 1~5 정수 부여

점수 가이드:
- 5: 팩트체커 판정과 거의 일치, 출처와 연결된 반박
- 4: 핵심은 맞으나 설명이 짧거나 출처 연결이 약함
- 3: 일부만 맞음
- 1~2: 근거 없음 또는 판정과 반대
"""


@dataclass(frozen=True)
class Stage3CorrectionEvaluation:
    why_rating: int
    ground_rating: int
    ai_feedback: str

    @property
    def turn_score(self) -> int:
        return round(((self.why_rating + self.ground_rating) / 10) * 100)


@dataclass(frozen=True)
class GEvalLlmConfig:
    chat_completions_url: str
    api_key: str
    model: str


def resolve_geval_llm_config() -> GEvalLlmConfig | None:
    if not settings.OPENAI_API_KEY.strip():
        return None
    return GEvalLlmConfig(
        chat_completions_url="https://api.openai.com/v1/chat/completions",
        api_key=settings.OPENAI_API_KEY.strip(),
        model=settings.OPENAI_CHAT_MODEL,
    )


def _reference_for_turn(turn: dict, debate_payload: dict | None) -> str:
    stored = find_turn_sources(
        debate_payload,
        turn_id=str(turn.get("id") or ""),
        claim=str(turn.get("claim") or ""),
    )
    if not stored:
        return ""
    lines = []
    for item in stored[:4]:
        title = str(item.get("title") or "").strip()
        source = str(item.get("source") or "").strip()
        if title:
            lines.append(f"- {title}" + (f" ({source})" if source else ""))
    return "\n".join(lines)


def _primary_verdict(turn: dict) -> tuple[str, str]:
    flawed = [
        item
        for item in (turn.get("claims") or [])
        if isinstance(item, dict) and str(item.get("verdict") or "") in NEEDS_CHECK
    ]
    if flawed:
        top = flawed[0]
        return str(top.get("verdict") or "unsupported"), str(top.get("reason") or turn.get("why") or "")
    return str(turn.get("verdict") or "unsupported"), str(turn.get("why") or "")


def _evaluate_correction_fallback(
    *,
    why_wrong: str,
    correct_ground: str,
    fact_checker_why: str,
    reference_sources: str,
) -> Stage3CorrectionEvaluation:
    why_tokens = tokens(why_wrong)
    ground_tokens = tokens(correct_ground)
    ref_tokens = tokens(reference_sources) | tokens(fact_checker_why)

    if len(why_tokens) < 3 or len(ground_tokens) < 3:
        return Stage3CorrectionEvaluation(
            why_rating=1,
            ground_rating=1,
            ai_feedback="틀린 이유와 맞는 근거를 조금 더 구체적으로 적어 주세요.",
        )

    why_hits = len(why_tokens & tokens(fact_checker_why))
    ground_hits = len(ground_tokens & ref_tokens)
    why_rating = max(1, min(5, round((why_hits / max(len(tokens(fact_checker_why)), 1)) * 5) or 1))
    ground_rating = max(1, min(5, round((ground_hits / max(len(ground_tokens), 1)) * 5) or 1))

    if why_hits >= 2 and ground_hits >= 2:
        why_rating = max(why_rating, 4)
        ground_rating = max(ground_rating, 4)

    feedback = "근거 설명이 팩트체커 판정과 부분적으로 맞습니다."
    if why_rating >= 4 and ground_rating >= 4:
        feedback = "틀린 이유와 맞는 근거를 잘 연결해 설명했습니다."
    elif why_rating <= 2:
        feedback = "왜 틀렸는지 팩트체커 판정과 연결해 다시 설명해 보세요."

    return Stage3CorrectionEvaluation(
        why_rating=why_rating,
        ground_rating=ground_rating,
        ai_feedback=feedback,
    )


async def _request_geval_json(
    *,
    llm_config: GEvalLlmConfig,
    system_prompt: str,
    user_prompt: str,
) -> dict:
    headers = {"Content-Type": "application/json", "Authorization": f"Bearer {llm_config.api_key}"}
    async with httpx.AsyncClient(timeout=120.0) as client:
        response = await client.post(
            llm_config.chat_completions_url,
            headers=headers,
            json={
                "model": llm_config.model,
                "temperature": 0.2,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        content = (
            response.json()
            .get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
    return _parse_json_content(content)


def _parse_json_content(content: str) -> dict:
    text = content.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


async def evaluate_stage3_correction(
    *,
    claim: str,
    verdict: str,
    fact_checker_why: str,
    highlight: str,
    why_wrong: str,
    correct_ground: str,
    reference_sources: str,
) -> Stage3CorrectionEvaluation:
    llm_config = resolve_geval_llm_config()
    if llm_config is not None:
        try:
            prompt = (
                f"{_CORRECTION_RUBRIC}\n\n"
                f"claim: {claim}\n"
                f"verdict: {verdict}\n"
                f"fact_checker_why: {fact_checker_why}\n"
                f"highlight: {highlight}\n"
                f"why_wrong: {why_wrong}\n"
                f"correct_ground: {correct_ground}\n"
                f"reference_sources:\n{reference_sources or '(없음)'}\n\n"
                'JSON만 출력: {"why_rating": 1-5, "ground_rating": 1-5, "feedback": "한국어 1~2문장"}'
            )
            parsed = await _request_geval_json(
                llm_config=llm_config,
                system_prompt="교육용 채점 judge. 요청한 JSON만 출력.",
                user_prompt=prompt,
            )
            why_rating = max(1, min(5, int(parsed.get("why_rating", 1))))
            ground_rating = max(1, min(5, int(parsed.get("ground_rating", 1))))
            feedback = str(parsed.get("feedback", "")).strip() or "근거 설명을 검토했습니다."
            return Stage3CorrectionEvaluation(
                why_rating=why_rating,
                ground_rating=ground_rating,
                ai_feedback=feedback,
            )
        except Exception:
            logger.exception("stage3 G-Eval correction failed; using fallback")

    return _evaluate_correction_fallback(
        why_wrong=why_wrong,
        correct_ground=correct_ground,
        fact_checker_why=fact_checker_why,
        reference_sources=reference_sources,
    )


async def grade_stage3_corrections(
    turns: list[dict],
    checked_ids: set[str],
    corrections: list[dict],
    *,
    debate_payload: dict | None = None,
) -> dict:
    """팩트체크한 의심 발언(caught)에 대해 why/ground G-Eval 채점."""

    correction_map = {
        str(item.get("turn_id") or "").strip(): item
        for item in corrections
        if str(item.get("turn_id") or "").strip()
    }
    rows: list[dict] = []
    turn_scores: list[int] = []

    for turn in turns:
        turn_id = str(turn.get("id") or "")
        if not turn_id or turn_id not in checked_ids or not turn_needs_check(turn):
            continue

        verdict, fact_why = _primary_verdict(turn)
        corr = correction_map.get(turn_id) or {}
        why_wrong = str(corr.get("why_wrong") or corr.get("why") or "").strip()
        correct_ground = str(corr.get("correct_ground") or corr.get("ground") or "").strip()
        highlight = str(corr.get("highlight") or "").strip()
        claim = str(turn.get("claim") or turn.get("text") or "")[:240]

        if len(why_wrong) < 8 or len(correct_ground) < 8:
            rows.append(
                {
                    "turn_id": turn_id,
                    "why_rating": 0,
                    "ground_rating": 0,
                    "turn_score": 0,
                    "feedback": "틀린 이유와 맞는 근거를 작성하지 않았습니다.",
                }
            )
            turn_scores.append(0)
            continue

        evaluation = await evaluate_stage3_correction(
            claim=claim,
            verdict=verdict,
            fact_checker_why=fact_why,
            highlight=highlight,
            why_wrong=why_wrong,
            correct_ground=correct_ground,
            reference_sources=_reference_for_turn(turn, debate_payload),
        )
        rows.append(
            {
                "turn_id": turn_id,
                "why_rating": evaluation.why_rating,
                "ground_rating": evaluation.ground_rating,
                "turn_score": evaluation.turn_score,
                "feedback": evaluation.ai_feedback,
            }
        )
        turn_scores.append(evaluation.turn_score)

    reasoning_score = round(sum(turn_scores) / len(turn_scores)) if turn_scores else 100
    return {
        "correction_rows": rows,
        "reasoning_score": reasoning_score,
        "graded_count": len(turn_scores),
    }
