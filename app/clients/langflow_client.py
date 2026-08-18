"""Langflow HTTP 클라이언트.

Stage 1/2는 `LANGFLOW_STAGE*_FLOW_ID`가 있으면 Langflow를 호출하고,
없으면(또는 호출 실패 시) OpenAI Chat으로 실응답을 생성한다.
OpenAI 키도 없을 때만 mock placeholder를 쓴다.

Stage 3는 Flow ID가 비어 있으면 엔드포인트 이름으로 한 번 조회하고,
그래도 없으면 mock 응답을 반환한다.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.exceptions import (
    Stage1LangflowServiceUnavailableError,
    Stage2LangflowServiceUnavailableError,
    Stage3LangflowServiceUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class Stage2LangflowResult:
    flawed_ai_response: str
    generated_errors: list[dict]


@dataclass
class Stage3LangflowResult:
    pro_argument: str
    con_argument: str
    fact_check: dict
    fact_check_raw: str
    rebuttal_argument: str = ""
    source: str = "mock"


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


class LangflowClient:
    async def run_stage1_chat(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        if settings.LANGFLOW_STAGE1_CHAT_FLOW_ID.strip():
            try:
                return await self._run_stage1_http(
                    message=message,
                    context=context,
                    temperature=temperature,
                )
            except Stage1LangflowServiceUnavailableError:
                logger.warning("stage1 langflow unavailable; trying OpenAI fallback")

        if settings.OPENAI_API_KEY.strip():
            return await self._openai_stage1_chat(
                message=message,
                context=context,
                temperature=temperature,
            )

        return self._mock_stage1_chat(
            message=message,
            context=context,
            temperature=temperature,
        )

    async def _run_stage1_http(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        prompt_node_id = settings.LANGFLOW_STAGE1_PROMPT_NODE_ID.strip()
        model_node_id = settings.LANGFLOW_STAGE1_MODEL_NODE_ID.strip()
        if not prompt_node_id or not model_node_id:
            raise Stage1LangflowServiceUnavailableError()

        payload = {
            "input_value": message,
            "input_type": "chat",
            "output_type": "chat",
            "tweaks": {
                prompt_node_id: {"context": context},
                model_node_id: {"temperature": temperature},
            },
        }
        url = (
            f"{settings.LANGFLOW_URL.rstrip('/')}"
            f"/api/v1/run/{settings.LANGFLOW_STAGE1_CHAT_FLOW_ID}"
        )
        headers = {"Content-Type": "application/json"}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("stage1 langflow HTTP failed")
            raise Stage1LangflowServiceUnavailableError() from exc

        text = self._parse_chat_output(data)
        if not text:
            raise Stage1LangflowServiceUnavailableError()
        return text

    def _parse_chat_output(self, data: dict) -> str:
        texts: list[str] = []
        for run_output in data.get("outputs", []):
            for inner in run_output.get("outputs", []):
                results = inner.get("results", {})
                message = results.get("message") or results.get("text")
                if isinstance(message, dict) and message.get("text"):
                    texts.append(str(message["text"]))
                elif isinstance(message, str) and message.strip():
                    texts.append(message)
        return texts[-1].strip() if texts else ""

    async def _openai_chat(
        self,
        *,
        system: str,
        user: str,
        temperature: float = 0.4,
        response_json: bool = False,
    ) -> str:
        if not settings.OPENAI_API_KEY.strip():
            raise Stage1LangflowServiceUnavailableError("OPENAI_API_KEY가 없습니다.")

        payload: dict = {
            "model": settings.OPENAI_CHAT_MODEL,
            "temperature": max(0.0, min(1.0, float(temperature))),
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        }
        if response_json:
            payload["response_format"] = {"type": "json_object"}

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                "https://api.openai.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.OPENAI_API_KEY}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = (
            data.get("choices", [{}])[0]
            .get("message", {})
            .get("content", "")
            .strip()
        )
        if not content:
            raise Stage1LangflowServiceUnavailableError("OpenAI 응답이 비어 있습니다.")
        return content

    async def _openai_stage1_chat(
        self, *, message: str, context: str, temperature: float
    ) -> str:
        system = (
            "당신은 중·고등학생 AI 리터러시 수업용 RAG 조교입니다. "
            "아래에 주어진 검색 컨텍스트만 근거로 한국어로 답하세요. "
            "컨텍스트에 없는 사실을 단정하지 말고, 없으면 부족하다고 말하세요."
        )
        user = (
            f"[검색 컨텍스트]\n{(context or '').strip() or '(없음)'}\n\n"
            f"[학생 질문]\n{(message or '').strip()}"
        )
        try:
            return await self._openai_chat(
                system=system,
                user=user,
                temperature=temperature,
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("stage1 OpenAI fallback failed")
            raise Stage1LangflowServiceUnavailableError() from exc

    def _mock_stage1_chat(
        self, *, message: str, context: str, temperature: float
    ) -> str:
        """Langflow·OpenAI 모두 불가할 때 placeholder."""

        snippets = [s.strip() for s in re.split(r"\n{2,}", context) if s.strip()]
        base_parts = (
            snippets[:3]
            if snippets
            else ["제공된 학습 자료에서 관련 내용을 찾지 못했습니다."]
        )
        lines = [
            f"질문('{message}')에 대해 검색된 자료를 바탕으로 답변합니다.",
            *base_parts,
        ]
        fillers = [
            "위 내용은 검색된 청크를 중심으로 정리한 것입니다.",
            "파라미터가 달라지면 검색 범위와 답변 톤도 함께 달라질 수 있습니다.",
            "학습 자료에 나온 사실을 우선적으로 언급했습니다.",
            "학생이 이해하기 쉬운 문장으로 풀어 썼습니다.",
            "추가 질문은 같은 자료 범위에서 다시 검색할 수 있습니다.",
            "자료에 없는 세부 일화는 온도가 높을 때 더 쉽게 섞일 수 있습니다.",
            "실제 운영에서는 Langflow 또는 OpenAI가 이 구간을 생성합니다.",
        ]
        while len(lines) < 10:
            lines.append(fillers[(len(lines) - 1) % len(fillers)])

        if temperature >= 0.7:
            lines.append(
                "참고로 자료에 직접 나오지 않은 배경 이야기도 섞어 설명할 수 있습니다. "
                "(고온 mock)"
            )
        return "\n".join(lines)

    async def run_stage2_hallucination(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
    ) -> Stage2LangflowResult:
        if settings.LANGFLOW_STAGE2_FLOW_ID.strip():
            try:
                return await self._run_stage2_http(
                    document_text=document_text,
                    question=question,
                    persona=persona,
                    hallucination_types=hallucination_types,
                    expected_error_count=expected_error_count,
                )
            except Stage2LangflowServiceUnavailableError:
                logger.warning("stage2 langflow unavailable; trying OpenAI fallback")

        if settings.OPENAI_API_KEY.strip():
            return await self._openai_stage2_hallucination(
                document_text=document_text,
                question=question,
                persona=persona,
                hallucination_types=hallucination_types,
                expected_error_count=expected_error_count,
            )

        return self._mock_stage2_hallucination(
            document_text=document_text,
            question=question,
            persona=persona,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
        )

    async def _run_stage2_http(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
    ) -> Stage2LangflowResult:
        gen_prompt_node_id = settings.LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID.strip()
        ext_prompt_node_id = settings.LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID.strip()
        if not gen_prompt_node_id or not ext_prompt_node_id:
            raise Stage2LangflowServiceUnavailableError()

        types_str = ", ".join(hallucination_types)
        count_str = str(expected_error_count)
        shared = {
            "document_text": document_text,
            "hallucination_types": types_str,
            "expected_error_count": count_str,
        }
        payload = {
            "input_value": "",
            "tweaks": {
                gen_prompt_node_id: {
                    **shared,
                    "question": question,
                    "persona": persona,
                },
                ext_prompt_node_id: shared,
            },
        }
        url = (
            f"{settings.LANGFLOW_URL.rstrip('/')}"
            f"/api/v1/run/{settings.LANGFLOW_STAGE2_FLOW_ID}"
        )
        headers = {"Content-Type": "application/json"}
        if settings.LANGFLOW_API_KEY:
            headers["x-api-key"] = settings.LANGFLOW_API_KEY

        try:
            async with httpx.AsyncClient(timeout=180.0) as client:
                response = await client.post(url, headers=headers, json=payload)
                response.raise_for_status()
                data = response.json()
        except httpx.HTTPError as exc:
            logger.exception("stage2 langflow HTTP failed")
            raise Stage2LangflowServiceUnavailableError() from exc

        return self._parse_stage2_outputs(data)

    def _parse_stage2_outputs(self, data: dict) -> Stage2LangflowResult:
        texts: list[str] = []
        for run_output in data.get("outputs", []):
            for inner in run_output.get("outputs", []):
                results = inner.get("results", {})
                message = results.get("message") or results.get("text")
                if isinstance(message, dict) and message.get("text"):
                    texts.append(message["text"])
                elif isinstance(message, str):
                    texts.append(message)

        if not texts:
            raise Stage2LangflowServiceUnavailableError()

        flawed = _strip_markdown(texts[0])
        errors: list[dict] = []
        if len(texts) > 1:
            raw = texts[1].strip()
            if raw.startswith("```"):
                raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                errors = parsed.get("generated_errors", [])
            elif isinstance(parsed, list):
                errors = parsed

        return Stage2LangflowResult(
            flawed_ai_response=flawed,
            generated_errors=errors,
        )

    async def _openai_stage2_hallucination(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
    ) -> Stage2LangflowResult:
        types_str = ", ".join(hallucination_types) or "RETRIEVAL_ERROR"
        doc = (document_text or "").strip()[:5000]
        system = (
            "당신은 AI 리터러시 교육용 환각(Hallucination) 생성기입니다. "
            "학생이 오류를 찾도록, 참고 문서를 바탕으로 의도적 오류가 섞인 한국어 답변을 만듭니다. "
            "반드시 JSON만 출력하세요."
        )
        user = (
            f"참고 문서:\n{doc or '(없음)'}\n\n"
            f"학생 질문: {question}\n"
            f"AI 페르소나: {persona}\n"
            f"사용할 환각 유형: {types_str}\n"
            f"넣을 오류 개수: {expected_error_count}\n\n"
            "출력 JSON 스키마:\n"
            "{\n"
            '  "flawed_ai_response": "오류가 포함된 전체 답변 문단",\n'
            '  "generated_errors": [\n'
            "    {\n"
            '      "error_sentence": "flawed_ai_response 안에 그대로 등장하는 오류 문장",\n'
            '      "error_type": "RETRIEVAL_ERROR|PERSONA_BIAS|INFORMATION_FABRICATION",\n'
            '      "correct_sentence": "문서 근거에 맞는 교정 문장",\n'
            '      "hallucination_reason": "왜 오류인지 한 줄",\n'
            '      "evidence_sentence": "참고 문서에서 근거가 되는 문장"\n'
            "    }\n"
            "  ]\n"
            "}\n"
            "규칙:\n"
            f"- generated_errors 길이는 정확히 {expected_error_count}개\n"
            "- error_sentence는 flawed_ai_response의 부분 문자열이어야 함\n"
            "- 답변은 자연스러운 서술형 한국어 문단으로 작성\n"
        )
        try:
            raw = await self._openai_chat(
                system=system,
                user=user,
                temperature=0.7,
                response_json=True,
            )
            parsed = _parse_json_object(raw)
            flawed = _strip_markdown(str(parsed.get("flawed_ai_response") or ""))
            errors_raw = parsed.get("generated_errors") or []
            if not isinstance(errors_raw, list):
                errors_raw = []

            errors: list[dict] = []
            for item in errors_raw[:expected_error_count]:
                if not isinstance(item, dict):
                    continue
                sentence = str(item.get("error_sentence") or "").strip()
                if not sentence:
                    continue
                start = flawed.find(sentence)
                if start < 0:
                    # 모델이 약간 변형한 경우 느슨하게 포함
                    start = 0
                end = start + len(sentence)
                error_type = str(item.get("error_type") or "RETRIEVAL_ERROR").strip().upper()
                if error_type not in {
                    "RETRIEVAL_ERROR",
                    "PERSONA_BIAS",
                    "INFORMATION_FABRICATION",
                }:
                    error_type = hallucination_types[0] if hallucination_types else "RETRIEVAL_ERROR"
                errors.append(
                    {
                        "error_sentence": sentence,
                        "error_type": error_type,
                        "start_index": start,
                        "end_index": end,
                        "correct_sentence": str(item.get("correct_sentence") or "").strip(),
                        "hallucination_reason": str(item.get("hallucination_reason") or "").strip(),
                        "evidence_sentence": str(item.get("evidence_sentence") or "").strip(),
                    }
                )

            if not flawed or not errors:
                raise Stage2LangflowServiceUnavailableError("OpenAI stage2 결과가 불완전합니다.")

            return Stage2LangflowResult(flawed_ai_response=flawed, generated_errors=errors)
        except Stage2LangflowServiceUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("stage2 OpenAI fallback failed")
            raise Stage2LangflowServiceUnavailableError() from exc

    def _mock_stage2_hallucination(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
    ) -> Stage2LangflowResult:
        """Langflow·OpenAI 모두 불가할 때 placeholder."""

        doc_preview = (document_text or "").strip()[:400]
        primary_type = hallucination_types[0] if hallucination_types else "RETRIEVAL_ERROR"
        secondary_type = (
            hallucination_types[1]
            if len(hallucination_types) > 1
            else "PERSONA_BIAS"
        )

        flawed_parts = [
            f"{doc_preview[:80]}...에 대한 답변입니다.",
            f"질문: {question}",
            f"페르소나 반영: {persona}",
            "장영실은 하늘을 나는 연을 발명했습니다.",
            "자격루라는 서양 기술을 도입했습니다.",
        ]
        flawed = " ".join(part for part in flawed_parts if part).strip()
        flawed = _strip_markdown(flawed)

        templates = [
            {
                "error_sentence": "하늘을 나는 연을 발명했습니다.",
                "error_type": "PERSONA_BIAS",
                "start_index": max(0, flawed.find("연을 발명")),
                "correct_sentence": "자격루와 측우기를 발명했습니다.",
                "hallucination_reason": "참고 문서에 없는 연 발명을 페르소나 편향으로 서술",
                "evidence_sentence": doc_preview[:120] or "문서에 자격루와 측우기가 언급됩니다.",
            },
            {
                "error_sentence": "서양 기술을 도입했습니다.",
                "error_type": "RETRIEVAL_ERROR",
                "start_index": max(0, flawed.find("서양 기술")),
                "correct_sentence": "조선의 독자적인 기술로 자격루를 발명했습니다.",
                "hallucination_reason": "원문과 반대로 서양 기술로 왜곡",
                "evidence_sentence": doc_preview[:120] or "문서에 조선의 독자적 기술로 기술됩니다.",
            },
            {
                "error_sentence": "세계 최초의 자동 물시계를 만들었다고 알려져 있습니다.",
                "error_type": "INFORMATION_FABRICATION",
                "start_index": 0,
                "correct_sentence": "자격루는 조선 시대에 발명된 물시계입니다.",
                "hallucination_reason": "문서에 없는 과장 표현 추가",
                "evidence_sentence": doc_preview[:120] or "문서 근거 문장",
            },
        ]

        errors: list[dict] = []
        for index in range(expected_error_count):
            item = dict(templates[index % len(templates)])
            if index == 1:
                item["error_type"] = secondary_type
            elif index == 0:
                item["error_type"] = primary_type
            start = item["start_index"]
            if start < 0:
                start = 0
            end = start + len(str(item["error_sentence"]))
            item["start_index"] = start
            item["end_index"] = end
            errors.append(item)

        return Stage2LangflowResult(
            flawed_ai_response=flawed,
            generated_errors=errors,
        )

    async def run_stage3_debate(
        self,
        *,
        topic: str,
        pro_persona: str = _DEFAULT_PRO_PERSONA,
        con_persona: str = _DEFAULT_CON_PERSONA,
        fact_persona: str = _DEFAULT_FACT_PERSONA,
        question: str | None = None,
        mode: str = "v2",
    ) -> Stage3LangflowResult:
        """Deprecated: Stage3LangflowClient.run_debate() 사용."""

        from app.clients.stage3_langflow_client import Stage3LangflowClient

        return await Stage3LangflowClient().run_debate(
            topic=topic,
            pro_persona=pro_persona,
            con_persona=con_persona,
            fact_persona=fact_persona,
            question=question,
            mode=mode,
        )

    async def _resolve_stage3_flow_id(self, mode: str) -> str:
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

    async def _run_stage3_http(
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
        input_value = topic.strip()
        if question and question.strip():
            input_value = f"{topic.strip()}\n\n학생 질문: {question.strip()}"

        payload: dict = {
            "input_value": input_value,
            "input_type": "chat",
            "output_type": "chat",
            "session_id": str(uuid.uuid4()),
        }
        # v2 con/rebut/fact는 상류 Prompt가 system_message를 넣는다.
        # tweaks로 덮으면 상대 발언 인용이 끊긴다.
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

        result = self._parse_stage3_outputs(data)
        result.source = "langflow"
        return result

    def _parse_stage3_outputs(self, data: dict) -> Stage3LangflowResult:
        """Deprecated: Stage3LangflowClient.parse_outputs() 사용."""

        from app.clients.stage3_langflow_client import Stage3LangflowClient

        return Stage3LangflowClient().parse_outputs(data)

    def _collect_outputs_by_component_id(self, data: dict) -> dict[str, str]:
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

    def _collect_chat_texts(self, data: dict) -> list[str]:
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

    def _mock_stage3_debate(
        self,
        *,
        topic: str,
        pro_persona: str,
        con_persona: str,
        fact_persona: str,
        question: str | None,
        mode: str = "v2",
    ) -> Stage3LangflowResult:
        """Langflow Flow ID 미설정 시 placeholder."""

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


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", text)
    cleaned = re.sub(r"[#*_>`]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()


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