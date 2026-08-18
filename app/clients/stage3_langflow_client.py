"""Stage 3 Langflow HTTP 클라이언트.

1·2단계 LangflowClient와 분리해, 3단계 토론·mock·503 정책만 담당한다.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.exceptions import Stage3LangflowServiceUnavailableError

logger = logging.getLogger(__name__)

_DEFAULT_PRO_PERSONA = "효율성을 강조하는 교육 전문가"
_DEFAULT_CON_PERSONA = "개인정보 침해를 우려하는 인권 전문가"
_DEFAULT_FACT_PERSONA = "중립적인 과학 기자"

_PRO_PROMPT = """당신은 EduFlow 3단계 토론의 **찬성 에이전트**입니다.
역할/성격: {persona}

규칙:
1. 토론 주제에 대해 찬성 입장만 주장하세요.
2. 근거 2~4개를 제시하되, 과장·허위 사실을 섞을 수 있습니다(학생이 팩트체크하도록).
3. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
4. 출력 형식:
【찬성 입장】
주장 요약: ...
핵심 근거:
1. ...
2. ...
예상 효과: ...
"""

_CON_PROMPT = """당신은 EduFlow 3단계 토론의 **반대 에이전트**입니다.
역할/성격: {persona}

규칙:
1. 토론 주제에 대해 반대 입장만 주장하세요.
2. 앞선 찬성 에이전트 주장의 허점·위험을 비판하세요.
3. 근거 2~4개를 제시하되, 과장·허위 사실을 섞을 수 있습니다.
4. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
5. 출력 형식:
【반대 입장】
주장 요약: ...
찬성 측 비판: ...
핵심 근거:
1. ...
2. ...
우려되는 점: ...
"""

_FACT_PROMPT = """당신은 EduFlow 3단계 토론의 **팩트체커 에이전트**입니다.
역할/성격: {persona}

중요:
- 입력에는 이미 【찬성 에이전트 주장】과 【반대 에이전트 주장】이 포함되어 있습니다.
- 반드시 그 두 주장을 **먼저 읽고 인용한 뒤**에만 팩트체크하세요.
- 찬성/반대 주장이 비어 있으면 검증하지 말고 오류를 보고하세요.

규칙:
1. 입력의 찬성·반대 주장에서 과장, 근거 부족, 사실 오류(환각)를 찾으세요.
2. 중립적으로 검증하세요. 결론을 대신 내리지 마세요.
3. 중·고등학생이 이해할 수 있는 한국어로 답하세요.
4. 반드시 아래 JSON만 출력하세요(다른 텍스트 금지):
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


@dataclass
class Stage3LangflowResult:
    pro_argument: str
    con_argument: str
    fact_check: dict
    fact_check_raw: str
    rebuttal_argument: str = ""
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

        parsed_fact = _parse_json_object(fact_raw) if fact_raw else {}
        return Stage3LangflowResult(
            pro_argument=pro_argument.strip(),
            con_argument=con_argument.strip(),
            rebuttal_argument=rebuttal_argument.strip(),
            fact_check=parsed_fact,
            fact_check_raw=(fact_raw or "").strip(),
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
            f"2. 오탐으로 무고한 학생이 부정행위자로 몰릴 위험이 있습니다.\n"
            f"우려되는 점: 감시 문화가 교실 신뢰를 무너뜨릴 수 있습니다."
        )
        rebuttal = ""
        if mode == "v2":
            rebuttal = (
                f"【재반박】\n"
                f"주장 요약: 동의 절차를 넣으면 '{topic}'을 도입할 수 있습니다.\n"
                f"보강 근거:\n"
                f"1. 감독에 쓰이던 교사의 시간을 채점과 피드백으로 돌릴 수 있습니다.\n"
                f"2. 민감정보는 별도 동의와 최소 수집으로 관리할 수 있습니다."
            )

        fact = {
            "topic": topic,
            "pro_argument": pro[:180],
            "con_argument": con[:180],
            "rebuttal_argument": rebuttal[:180] if rebuttal else "",
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
                }
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
        if rebuttal:
            fact["pro_claims_checked"].append(
                {
                    "claim": "감독에 쓰이던 교사의 시간을 채점과 피드백으로 돌릴 수 있습니다.",
                    "verdict": "supported",
                    "reason": "과장된 수치 없이 제시되었고 논리적으로 무리가 없다",
                }
            )

        return Stage3LangflowResult(
            pro_argument=pro,
            con_argument=con,
            rebuttal_argument=rebuttal,
            fact_check=fact,
            fact_check_raw=json.dumps(fact, ensure_ascii=False),
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
