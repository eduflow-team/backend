"""Stage 3 Langflow HTTP 클라이언트.

1·2단계 LangflowClient와 분리해, 3단계 토론·mock·503 정책만 담당한다.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass, field

import httpx

from app.core.config import settings
from app.core.exceptions import Stage3LangflowServiceUnavailableError

logger = logging.getLogger(__name__)

_DEFAULT_PRO_PERSONA = "효율성을 강조하는 교육 전문가"
_DEFAULT_CON_PERSONA = "개인정보 침해를 우려하는 인권 전문가"
_DEFAULT_FACT_PERSONA = "중립적인 과학 기자"

_FLAW_TYPES = (
    "과장된 수치·통계, 허위/조작된 사실, "
    "출처·기관명 없는 '연구에 따르면' 식 단정, "
    "근거 없는 일반화, 잘못된 기관·법령 인용"
)

_FLAW_INSERTION_RULE = f"""토론 **전체** 근거 중 **약 25~35%(2~3개)**만 의도적 오류로 넣고, **나머지는 사실에 가깝고 검증 가능한 정상 근거**로 작성하세요.
- 허용 오류 유형: {_FLAW_TYPES}
- 오류는 핵심 근거 목록에 자연스럽게 섞고, 발언마다 최대 1개씩 분산하세요.
- 오류만 잔뜩 넣지 말고, supported로 볼 수 있는 근거가 **최소 4개 이상** 있어야 합니다."""

_DEBATE_QUALITY_NOTE = f"""[토론 품질]
찬성·반대·반론·결론을 합친 **전체 토론**에 의도적 오류(과장, 허위, 출처·기관 미언급 등) **2~3개**와, 검증 가능한 **정상 근거 4개 이상**이 함께 포함되어야 합니다.
"""

_PRO_PROMPT = """당신은 EduFlow 3단계 토론의 **찬성 에이전트**입니다.
역할/성격: {persona}

규칙:
1. 토론 주제에 대해 찬성 입장만 주장하세요.
2. 근거 2~4개를 제시하세요.
3. {_flaw_rule}
4. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
5. 출력 형식:
【찬성 입장】
주장 요약: ...
핵심 근거:
1. ...
2. ...
예상 효과: ...
""".replace("{_flaw_rule}", _FLAW_INSERTION_RULE)

_CON_PROMPT = """당신은 EduFlow 3단계 토론의 **반대 에이전트**입니다.
역할/성격: {persona}

규칙:
1. 토론 주제에 대해 반대 입장만 주장하세요.
2. 앞선 찬성 에이전트 주장의 허점·위험을 비판하세요.
3. 근거 2~4개를 제시하세요.
4. {_flaw_rule}
5. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
6. 출력 형식:
【반대 입장】
주장 요약: ...
찬성 측 비판: ...
핵심 근거:
1. ...
2. ...
우려되는 점: ...
""".replace("{_flaw_rule}", _FLAW_INSERTION_RULE)

_FACT_PROMPT = """당신은 EduFlow 3단계 토론의 **팩트체커 에이전트**입니다.
역할/성격: {persona}

중요:
- 입력에는 이미 【찬성 에이전트 주장】과 【반대 에이전트 주장】이 포함되어 있습니다.
- 반드시 그 두 주장을 **먼저 읽고 인용한 뒤**에만 팩트체크하세요.
- 찬성/반대 주장이 비어 있으면 검증하지 말고 오류를 보고하세요.

규칙:
1. 입력의 찬성·반대 주장에서 과장, 근거 부족, 사실 오류(환각), **출처·기관명 없는 단정**을 찾으세요.
2. `unsupported`는 근거·기관·연구명이 없는 단정, `exaggerated`는 과장된 수치, `false`는 사실과 다른 내용에 쓰세요.
3. 중립적으로 검증하세요. 결론을 대신 내리지 마세요.
4. 찬성·반대 주장의 **주요 근거를 빠짐없이** pro/con_claims_checked에 넣으세요.
5. exaggerated·unsupported·false는 **2~3개**만, supported는 **최소 4개 이상** 포함하세요.
6. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
7. 반드시 아래 JSON만 출력하세요(다른 텍스트 금지):
{{
  "topic": "토론 주제",
  "pro_argument": "입력에서 받은 찬성 주장 요약",
  "con_argument": "입력에서 받은 반대 주장 요약",
  "pro_claims_checked": [{{"claim": "...", "verdict": "supported|exaggerated|unsupported|false", "reason": "..."}}],
  "con_claims_checked": [{{"claim": "...", "verdict": "supported|exaggerated|unsupported|false", "reason": "..."}}],
  "reliable_points": ["..."],
  "unreliable_points": ["..."],
  "balanced_summary": "양측 비교 요약",
  "student_guide": "학생이 보고서를 쓸 때 확인할 질문 2~3개"
}}
"""

_FINAL_FACT_PROMPT = """당신은 EduFlow 3단계 토론의 **팩트체커 에이전트**입니다.
역할/성격: {persona}

아래는 입론·반론·최종 변론까지 이어진 **전체 토론 기록**입니다. 새 주장을 만들지 말고, 기록만 검증하세요.

{transcript}

규칙:
1. 위 전체 토론에서 과장, 근거 부족, 사실 오류, **출처·기관명 없는 단정**을 찾으세요.
2. 문제 있는 주장을 pro_claims_checked 또는 con_claims_checked에 넣고, verdict는 supported|exaggerated|unsupported|false 중 하나로 표시하세요.
3. exaggerated·unsupported·false는 **2~3개**, supported는 **최소 4개 이상** 반드시 포함하세요.
4. 반드시 JSON만 출력하세요:
{{
  "topic": "{topic}",
  "pro_argument": "찬성 측 요지",
  "con_argument": "반대 측 요지",
  "pro_claims_checked": [{{"claim": "...", "verdict": "...", "reason": "..."}}],
  "con_claims_checked": [{{"claim": "...", "verdict": "...", "reason": "..."}}],
  "reliable_points": ["..."],
  "unreliable_points": ["..."],
  "balanced_summary": "...",
  "student_guide": "..."
}}
"""


@dataclass
class Stage3LangflowResult:
    pro_argument: str
    con_argument: str
    fact_check: dict
    fact_check_raw: str
    rebuttal_argument: str = ""
    speeches: dict[str, str] = field(default_factory=dict)
    source: str = "mock"


class Stage3LangflowClient:
    async def run_debate(
        self,
        *,
        topic: str,
        pro_persona: str = _DEFAULT_PRO_PERSONA,
        con_persona: str = _DEFAULT_CON_PERSONA,
        fact_persona: str = _DEFAULT_FACT_PERSONA,
        question: str | None = None,
        mode: str = "v2",
    ) -> Stage3LangflowResult:
        debate_mode = (mode or "v2").strip().lower()
        if debate_mode not in {"v1", "v2"}:
            debate_mode = "v2"

        if debate_mode == "v2":
            v1_id = await self._resolve_flow_id("v1")
            if v1_id:
                return await self._run_six_round(
                    topic=topic,
                    pro_persona=pro_persona,
                    con_persona=con_persona,
                    fact_persona=fact_persona,
                    question=question,
                    flow_id=v1_id,
                )

        flow_id = await self._resolve_flow_id(debate_mode)
        if flow_id:
            return await self._run_http(
                topic=topic,
                pro_persona=pro_persona,
                con_persona=con_persona,
                fact_persona=fact_persona,
                question=question,
                mode=debate_mode,
                flow_id=flow_id,
            )

        if settings.STAGE3_ALLOW_MOCK:
            return self._mock_debate(
                topic=topic,
                pro_persona=pro_persona,
                con_persona=con_persona,
                fact_persona=fact_persona,
                question=question,
                mode=debate_mode,
            )

        raise Stage3LangflowServiceUnavailableError()

    async def _resolve_flow_id(self, mode: str) -> str:
        if mode == "v2":
            configured = (
                settings.LANGFLOW_STAGE3_V2_FLOW_ID.strip()
                or settings.LANGFLOW_STAGE3_FLOW_ID.strip()
            )
            endpoint = settings.LANGFLOW_STAGE3_V2_ENDPOINT.strip()
        else:
            configured = settings.LANGFLOW_STAGE3_FLOW_ID.strip()
            endpoint = settings.LANGFLOW_STAGE3_V1_ENDPOINT.strip()
        if configured:
            return configured
        return await self._lookup_flow_id_by_endpoint(endpoint)

    async def _lookup_flow_id_by_endpoint(self, endpoint: str) -> str:
        if not endpoint:
            return ""
        url = f"{settings.LANGFLOW_URL.rstrip('/')}/api/v1/flows/?get_all=true"
        headers: dict[str, str] = {}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY
        try:
            async with httpx.AsyncClient(timeout=15.0) as client:
                response = await client.get(url, headers=headers)
                response.raise_for_status()
                flows = response.json()
        except httpx.HTTPError:
            logger.warning("stage3 langflow flow lookup failed for %s", endpoint)
            return ""
        if not isinstance(flows, list):
            return ""
        for item in flows:
            if isinstance(item, dict) and item.get("endpoint_name") == endpoint:
                return str(item.get("id") or "")
        return ""

    @staticmethod
    def _agent_sys(side: str, persona: str, duty: str, *, heading: str) -> str:
        label = "찬성" if side == "pro" else "반대"
        other = "반대" if side == "pro" else "찬성"
        return f"""당신은 EduFlow 3단계 토론의 **{label} 에이전트**입니다.
역할/성격: {persona}

지금 할 일: {duty}

규칙:
1. {label} 입장만 말하세요. {other} 입장을 취하지 마세요.
2. 근거 2~3개를 제시하세요.
3. {_FLAW_INSERTION_RULE}
4. 상대 발언을 인용할 때는 한 문장만 짧게 인용하세요.
5. 중·고등학생이 이해할 수 있는 한국어로, 아래 형식으로만 답하세요:
【{heading}】
주장 요약: ...
핵심 근거:
1. ...
2. ...
마무리: ...
"""

    @staticmethod
    def _hold_sys(side: str, persona: str) -> str:
        label = "찬성" if side == "pro" else "반대"
        return f"""당신은 EduFlow 3단계 토론의 **{label} 에이전트**입니다.
역할/성격: {persona}
지금은 당신 차례가 아닙니다. 아래 형식만 출력하세요.
【{label} 입장】
주장 요약: (이번 차례 아님)
핵심 근거:
1. (없음)
마무리: 없음
"""

    async def _post_run(self, flow_id: str, payload: dict) -> dict:
        url = f"{settings.LANGFLOW_URL.rstrip('/')}/api/v1/run/{flow_id}"
        headers = {"Content-Type": "application/json"}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY
        try:
            async with httpx.AsyncClient(timeout=240.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                return response.json()
        except httpx.HTTPError as exc:
            logger.exception("stage3 langflow HTTP failed")
            raise Stage3LangflowServiceUnavailableError() from exc

    async def _run_v1_outputs(self, flow_id: str, input_value: str, tweaks: dict) -> dict[str, str]:
        payload = {
            "input_value": input_value,
            "input_type": "chat",
            "output_type": "chat",
            "session_id": str(uuid.uuid4()),
            "tweaks": tweaks,
        }
        data = await self._post_run(flow_id, payload)
        return self._collect_outputs_by_component_id(data)

    async def _run_six_round(
        self,
        *,
        topic: str,
        pro_persona: str,
        con_persona: str,
        fact_persona: str,
        question: str | None,
        flow_id: str,
    ) -> Stage3LangflowResult:
        from app.services.stage3_debate import (
            MIN_DEBATE_FLAWS,
            balance_fact_claims,
            count_flaw_claims,
            merge_facts,
            parse_fact_json,
        )

        extra = f"\n학생 질문: {question.strip()}" if question and question.strip() else ""
        quality = _DEBATE_QUALITY_NOTE
        pro_id = settings.LANGFLOW_STAGE3_PRO_AGENT_ID.strip() or "LM-s3pro"
        con_id = settings.LANGFLOW_STAGE3_CON_AGENT_ID.strip() or "LM-s3con"

        def need(out: dict[str, str], node: str, label: str) -> str:
            text = (out.get(node) or "").strip()
            if not text or "(이번 차례 아님)" in text:
                raise Stage3LangflowServiceUnavailableError(
                    f"Langflow가 {label} 발언을 비워 두었습니다."
                )
            return text

        out1 = await self._run_v1_outputs(
            flow_id,
            f"{quality}논제: {topic}\n찬성 측 페르소나: {pro_persona}\n반대 측 페르소나: {con_persona}{extra}\n지금은 입론입니다.",
            {
                pro_id: {
                    "system_message": self._agent_sys(
                        "pro",
                        pro_persona,
                        "찬성 측 입론을 하세요. 논제를 정의하고, 배경을 짧게 설명한 뒤, 주요 주장과 근거를 제시하세요.",
                        heading="찬성 측 입론",
                    )
                },
                con_id: {
                    "system_message": self._agent_sys(
                        "con",
                        con_persona,
                        "반대 측 입론을 하세요. 반대 입장의 주요 주장과 근거를 제시하세요. 찬성 측을 인용하지 마세요.",
                        heading="반대 측 입론",
                    )
                },
            },
        )
        pro_open = need(out1, "ChatOutput-s3pro", "찬성 측 입론")
        con_open = need(out1, "ChatOutput-s3con", "반대 측 입론")
        fact1 = parse_fact_json(out1.get("ChatOutput-s3fact", ""))

        out2 = await self._run_v1_outputs(
            flow_id,
            (
                f"{quality}논제: {topic}\n\n【입론 · 찬성 측】\n{pro_open}\n\n"
                f"【입론 · 반대 측】\n{con_open}\n\n지금은 반론입니다. 반대 에이전트만 발언하세요."
            ),
            {
                pro_id: {"system_message": self._hold_sys("pro", pro_persona)},
                con_id: {
                    "system_message": self._agent_sys(
                        "con",
                        con_persona,
                        "반대 측 반론을 하세요. 찬성 측 입론의 허점이나 근거의 타당성을 지적하세요.",
                        heading="반대 측 반론",
                    )
                },
            },
        )
        con_rebut = need(out2, "ChatOutput-s3con", "반대 측 반론")
        fact2 = parse_fact_json(out2.get("ChatOutput-s3fact", ""))

        out3 = await self._run_v1_outputs(
            flow_id,
            (
                f"{quality}논제: {topic}\n\n【입론 · 찬성 측】\n{pro_open}\n\n"
                f"【입론 · 반대 측】\n{con_open}\n\n【반론 · 반대 측】\n{con_rebut}\n\n"
                "지금은 반론입니다. 찬성 에이전트만 발언하세요."
            ),
            {
                pro_id: {
                    "system_message": self._agent_sys(
                        "pro",
                        pro_persona,
                        "찬성 측 반론을 하세요. 반대 측 반론을 재반박하고 찬성 측 입론을 강화하세요.",
                        heading="찬성 측 반론",
                    )
                },
                con_id: {"system_message": self._hold_sys("con", con_persona)},
            },
        )
        pro_rebut = need(out3, "ChatOutput-s3pro", "찬성 측 반론")
        fact3 = parse_fact_json(out3.get("ChatOutput-s3fact", ""))

        out4 = await self._run_v1_outputs(
            flow_id,
            (
                f"{quality}논제: {topic}\n\n【입론 · 찬성 측】\n{pro_open}\n\n"
                f"【입론 · 반대 측】\n{con_open}\n\n【반론 · 반대 측】\n{con_rebut}\n\n"
                f"【반론 · 찬성 측】\n{pro_rebut}\n\n지금은 최종 변론입니다."
            ),
            {
                pro_id: {
                    "system_message": self._agent_sys(
                        "pro",
                        pro_persona,
                        "찬성 측 최종 변론을 하세요. 핵심 쟁점을 정리하고 찬성 입장을 강조하세요. 당신이 마지막 발언입니다.",
                        heading="찬성 측 최종 변론",
                    )
                },
                con_id: {
                    "system_message": self._agent_sys(
                        "con",
                        con_persona,
                        "반대 측 최종 변론을 하세요. 핵심 쟁점을 정리하고 반대 입장을 강조하세요.",
                        heading="반대 측 최종 변론",
                    )
                },
            },
        )
        con_close = need(out4, "ChatOutput-s3con", "반대 측 최종 변론")
        pro_close = need(out4, "ChatOutput-s3pro", "찬성 측 최종 변론")
        fact4 = parse_fact_json(out4.get("ChatOutput-s3fact", ""))

        speeches = {
            "pro_open": pro_open,
            "con_open": con_open,
            "con_rebut": con_rebut,
            "pro_rebut": pro_rebut,
            "con_rerebut": con_close,
            "pro_rerebut": pro_close,
        }
        merged = merge_facts(fact1, fact2, fact3, fact4)
        if count_flaw_claims(merged) < MIN_DEBATE_FLAWS:
            logger.warning(
                "stage3 debate has fewer than %d flaw claims (%d); running full transcript fact-check",
                MIN_DEBATE_FLAWS,
                count_flaw_claims(merged),
            )
            supplemental = await self._run_full_transcript_factcheck(
                flow_id=flow_id,
                topic=topic,
                speeches=speeches,
                fact_persona=fact_persona,
                pro_persona=pro_persona,
                con_persona=con_persona,
            )
            if supplemental:
                merged = merge_facts(merged, supplemental)
        merged = balance_fact_claims(merged, speeches) or merged

        return Stage3LangflowResult(
            pro_argument=pro_open,
            con_argument=con_open,
            rebuttal_argument=pro_rebut,
            fact_check=merged,
            fact_check_raw=json.dumps(merged, ensure_ascii=False),
            speeches=speeches,
            source="langflow",
        )

    _SPEECH_LABELS = {
        "pro_open": "입론 · 찬성 측",
        "con_open": "입론 · 반대 측",
        "con_rebut": "반론 · 반대 측",
        "pro_rebut": "반론 · 찬성 측",
        "con_rerebut": "최종 변론 · 반대 측",
        "pro_rerebut": "최종 변론 · 찬성 측",
    }

    async def _run_full_transcript_factcheck(
        self,
        *,
        flow_id: str,
        topic: str,
        speeches: dict[str, str],
        fact_persona: str,
        pro_persona: str,
        con_persona: str,
    ) -> dict | None:
        from app.services.stage3_debate import parse_fact_json

        pro_id = settings.LANGFLOW_STAGE3_PRO_AGENT_ID.strip() or "LM-s3pro"
        con_id = settings.LANGFLOW_STAGE3_CON_AGENT_ID.strip() or "LM-s3con"
        fact_id = settings.LANGFLOW_STAGE3_FACT_AGENT_ID.strip() or "LM-s3fact"
        transcript = "\n\n".join(
            f"【{self._SPEECH_LABELS.get(role, role)}】\n{text.strip()}"
            for role, text in speeches.items()
            if text and text.strip()
        )
        out = await self._run_v1_outputs(
            flow_id,
            "위 전체 토론 기록을 팩트체크하세요.",
            {
                pro_id: {"system_message": self._hold_sys("pro", pro_persona)},
                con_id: {"system_message": self._hold_sys("con", con_persona)},
                fact_id: {
                    "system_message": _FINAL_FACT_PROMPT.format(
                        persona=fact_persona,
                        topic=topic.replace('"', "'"),
                        transcript=transcript,
                    )
                },
            },
        )
        return parse_fact_json(out.get("ChatOutput-s3fact", ""))

    async def _run_http(
        self,
        *,
        topic: str,
        pro_persona: str,
        con_persona: str,
        fact_persona: str,
        question: str | None,
        mode: str,
        flow_id: str,
    ) -> Stage3LangflowResult:
        payload: dict = {
            "input_value": self._build_input_value(
                topic=topic,
                pro_persona=pro_persona,
                con_persona=con_persona,
                fact_persona=fact_persona,
                question=question,
            ),
            "input_type": "chat",
            "output_type": "chat",
            "session_id": str(uuid.uuid4()),
        }
        # v2 con/rebut/fact는 상류 Prompt가 system_message를 넣는다.
        # tweaks로 LM system_message를 덮으면 상대 발언 인용이 끊긴다.
        if mode == "v1":
            pro_id = settings.LANGFLOW_STAGE3_PRO_AGENT_ID.strip() or "LM-s3pro"
            con_id = settings.LANGFLOW_STAGE3_CON_AGENT_ID.strip() or "LM-s3con"
            fact_id = settings.LANGFLOW_STAGE3_FACT_AGENT_ID.strip() or "LM-s3fact"
            payload["tweaks"] = {
                pro_id: {"system_message": _PRO_PROMPT.format(persona=pro_persona)},
                con_id: {"system_message": _CON_PROMPT.format(persona=con_persona)},
                fact_id: {"system_message": _FACT_PROMPT.format(persona=fact_persona)},
            }

        url = f"{settings.LANGFLOW_URL.rstrip('/')}/api/v1/run/{flow_id}"
        headers = {"Content-Type": "application/json"}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY

        try:
            async with httpx.AsyncClient(timeout=240.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("stage3 langflow HTTP failed")
            raise Stage3LangflowServiceUnavailableError() from exc

        result = self.parse_outputs(data)
        result.source = "langflow"
        return result

    @staticmethod
    def _build_input_value(
        *,
        topic: str,
        pro_persona: str,
        con_persona: str,
        fact_persona: str,
        question: str | None,
    ) -> str:
        lines = [
            f"논제: {topic.strip()}",
            f"찬성 측 페르소나: {pro_persona.strip()}",
            f"반대 측 페르소나: {con_persona.strip()}",
            f"팩트체커 페르소나: {fact_persona.strip()}",
        ]
        if question and question.strip():
            lines.append(f"학생 질문: {question.strip()}")
        return "\n".join(lines)

    def parse_outputs(self, data: dict) -> Stage3LangflowResult:
        by_id = self._collect_outputs_by_component_id(data)
        texts = self._collect_chat_texts(data)
        if not by_id and not texts:
            raise Stage3LangflowServiceUnavailableError()

        pro_argument = (
            by_id.get("ChatOutput-v2pro")
            or by_id.get("ChatOutput-s3pro")
            or (texts[0] if texts else "")
        )
        con_argument = (
            by_id.get("ChatOutput-v2con")
            or by_id.get("ChatOutput-s3con")
            or (texts[1] if len(texts) > 1 else "")
        )
        rebuttal_argument = by_id.get("ChatOutput-v2rebut") or ""
        fact_raw = (
            by_id.get("ChatOutput-v2fact")
            or by_id.get("ChatOutput-s3fact")
            or (texts[-1] if texts else "")
        )

        if not pro_argument.strip() and not con_argument.strip():
            raise Stage3LangflowServiceUnavailableError()

        from app.services.stage3_debate import balance_fact_claims

        parsed_fact = _parse_json_object(fact_raw) if fact_raw else {}
        speeches = {
            "pro_open": pro_argument.strip(),
            "con_open": con_argument.strip(),
            "pro_rebut": rebuttal_argument.strip(),
        }
        parsed_fact = balance_fact_claims(parsed_fact, speeches) or parsed_fact
        return Stage3LangflowResult(
            pro_argument=pro_argument.strip(),
            con_argument=con_argument.strip(),
            rebuttal_argument=rebuttal_argument.strip(),
            fact_check=parsed_fact,
            fact_check_raw=(fact_raw or "").strip(),
            speeches=speeches,
            source="langflow",
        )

    @staticmethod
    def _collect_outputs_by_component_id(data: dict) -> dict[str, str]:
        found: dict[str, str] = {}
        for run_output in data.get("outputs") or []:
            for inner in run_output.get("outputs") or []:
                component_id = inner.get("component_id") or ""
                results = inner.get("results") or {}
                message = results.get("message") or results.get("text")
                text = ""
                if isinstance(message, dict) and message.get("text"):
                    text = str(message["text"])
                elif isinstance(message, str) and message.strip():
                    text = message
                if component_id and text:
                    found[str(component_id)] = text
        return found

    @staticmethod
    def _collect_chat_texts(data: dict) -> list[str]:
        texts: list[str] = []
        for run_output in data.get("outputs", []):
            for inner in run_output.get("outputs", []):
                results = inner.get("results", {})
                message = results.get("message") or results.get("text")
                if isinstance(message, dict) and message.get("text"):
                    texts.append(str(message["text"]))
                elif isinstance(message, str) and message.strip():
                    texts.append(message)
        return texts

    def _mock_debate(
        self,
        *,
        topic: str,
        pro_persona: str,
        con_persona: str,
        fact_persona: str,
        question: str | None,
        mode: str = "v2",
    ) -> Stage3LangflowResult:
        q = (question or "").strip()
        pro = (
            f"【찬성 입장】\n"
            f"주장 요약: '{topic}'에 찬성합니다. ({pro_persona})\n"
            f"핵심 근거:\n"
            f"1. AI 감독은 부정행위를 90% 이상 줄인다는 연구 결과가 있습니다.\n"
            f"2. 교사 채점·감독 부담을 크게 줄여 수업 질이 올라갑니다.\n"
            f"예상 효과: 공정한 시험 환경과 행정 효율을 동시에 확보할 수 있습니다."
        )
        if q:
            pro += f"\n추가 응답(학생 질문): {q}"

        con = (
            f"【반대 입장】\n"
            f"주장 요약: '{topic}'에 반대합니다. ({con_persona})\n"
            f"찬성 측 비판: '부정행위 90% 감소'는 근거가 불명확하고 과장일 수 있습니다.\n"
            f"핵심 근거:\n"
            f"1. 얼굴·시선 데이터 수집은 학생 개인정보를 과도하게 침해합니다.\n"
            f"2. 전국 학교의 80%가 이미 AI 감독을 도입했다는 보고가 있습니다.\n"
            f"우려되는 점: 감시 문화가 교실 신뢰를 무너뜨릴 수 있습니다."
        )
        rebuttal = (
            f"【반론 · 찬성 측】\n"
            f"주장 요약: 동의 절차를 넣으면 '{topic}'을 도입할 수 있습니다.\n"
            f"핵심 근거:\n"
            f"1. 감독에 쓰이던 교사의 시간을 채점과 피드백으로 돌릴 수 있습니다.\n"
            f"2. 민감정보는 별도 동의와 최소 수집으로 관리할 수 있습니다."
        )
        con_rebut = (
            f"【반론 · 반대 측】\n"
            f"주장 요약: 90% 감소라는 숫자는 도입을 정당화하기에 부족합니다.\n"
            f"핵심 근거:\n"
            f"1. 시험이 끝난 뒤에도 얼굴 데이터가 남아 있으면 목적 외 이용 위험이 있습니다.\n"
            f"2. 오탐으로 무고한 학생이 부정행위자로 몰릴 수 있습니다."
        )
        con_close = (
            f"【최종 변론 · 반대 측】\n"
            f"주장 요약: 동의서를 받는다고 감시가 사라지지는 않습니다.\n"
            f"핵심 근거:\n"
            f"1. 동의를 거부한 학생을 별도 고사장에 두면 낙인 효과가 생길 수 있습니다.\n"
            f"2. 핵심 쟁점은 개인정보와 교실 신뢰입니다."
        )
        pro_close = (
            f"【최종 변론 · 찬성 측】\n"
            f"주장 요약: 대안 고사장을 같은 조건으로 운영하면 낙인을 줄일 수 있습니다.\n"
            f"핵심 근거:\n"
            f"1. 거부 학생을 위한 대안 고사장을 같은 시험 조건으로 운영할 수 있습니다.\n"
            f"2. 마지막까지 공정성과 효율을 함께 설계하는 것이 찬성 입장입니다."
        )

        fact = {
            "topic": topic,
            "pro_argument": pro[:180],
            "con_argument": con[:180],
            "rebuttal_argument": rebuttal[:180],
            "pro_claims_checked": [
                {
                    "claim": "AI 감독은 부정행위를 90% 이상 줄인다는 연구 결과가 있습니다.",
                    "verdict": "exaggerated",
                    "reason": "구체적 출처·연구 조건이 제시되지 않음",
                }
            ],
            "con_claims_checked": [
                {
                    "claim": "얼굴·시선 데이터 수집은 학생 개인정보를 과도하게 침해합니다.",
                    "verdict": "supported",
                    "reason": "생체·행동 데이터는 민감정보로 분류되는 경우가 많음",
                },
                {
                    "claim": "전국 학교의 80%가 이미 AI 감독을 도입했다는 보고가 있습니다.",
                    "verdict": "false",
                    "reason": "출처·기관명 없이 전국 도입률을 단정한 수치로 보임",
                },
            ],
            "reliable_points": [
                "개인정보·오탐 리스크는 검토할 가치가 있다",
                "감독 효율화라는 찬성 논리 자체는 일리가 있다",
            ],
            "unreliable_points": [
                "부정행위 90% 감소 수치는 과장으로 보인다",
            ],
            "balanced_summary": (
                f"'{topic}'은 효율과 인권이 충돌하는 주제다. "
                f"수치 주장은 검증이 필요하고, 개인정보 위험은 상대적으로 구체적이다. "
                f"(팩트체커: {fact_persona})"
            ),
            "student_guide": [
                "찬성 측 수치의 출처를 요구했는가?",
                "반대 측 개인정보 주장을 구체 사례로 확인했는가?",
                "최종 결론에 양측 근거를 균형 있게 썼는가?",
            ],
        }
        if mode != "v1":
            fact["con_claims_checked"].append(
                {
                    "claim": "시험이 끝난 뒤에도 얼굴 데이터가 남아 있으면 목적 외 이용 위험이 있습니다.",
                    "verdict": "supported",
                    "reason": "개인정보는 수집 목적 범위에서만 이용·보관해야 한다",
                }
            )
            fact["pro_claims_checked"].append(
                {
                    "claim": "감독에 쓰이던 교사의 시간을 채점과 피드백으로 돌릴 수 있습니다.",
                    "verdict": "supported",
                    "reason": "과장된 수치 없이 제시되었고 논리적으로 무리가 없다",
                }
            )

        speeches = {
            "pro_open": pro,
            "con_open": con,
        }
        if mode != "v1":
            speeches.update(
                {
                    "con_rebut": con_rebut,
                    "pro_rebut": rebuttal,
                    "con_rerebut": con_close,
                    "pro_rerebut": pro_close,
                }
            )

        from app.services.stage3_debate import balance_fact_claims

        fact = balance_fact_claims(fact, speeches) or fact

        return Stage3LangflowResult(
            pro_argument=pro,
            con_argument=con,
            rebuttal_argument=rebuttal if mode != "v1" else "",
            fact_check=fact,
            fact_check_raw=json.dumps(fact, ensure_ascii=False),
            speeches=speeches,
            source="mock",
        )


def _parse_json_object(text: str) -> dict:
    raw = text.strip()
    if raw.startswith("```"):
        raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        match = re.search(r"\{[\s\S]*\}", raw)
        if match:
            try:
                parsed = json.loads(match.group(0))
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                pass
    return {"raw": raw}
