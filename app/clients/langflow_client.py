"""Langflow HTTP 클라이언트.

`LANGFLOW_STAGE*_FLOW_ID`가 비어 있으면 mock 응답을 반환한다.
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx

from app.core.config import settings
from app.core.exceptions import (
    Stage1LangflowServiceUnavailableError,
    Stage2LangflowServiceUnavailableError,
)

logger = logging.getLogger(__name__)


@dataclass
class Stage2LangflowResult:
    flawed_ai_response: str
    generated_errors: list[dict]


class LangflowClient:
    async def run_stage1_chat(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        if settings.LANGFLOW_STAGE1_CHAT_FLOW_ID.strip():
            return await self._run_stage1_http(
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

    def _mock_stage1_chat(
        self, *, message: str, context: str, temperature: float
    ) -> str:
        """Langflow Flow ID 미설정 시 placeholder."""

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
            "실제 운영에서는 Langflow가 이 구간을 생성합니다.",
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
            return await self._run_stage2_http(
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

    def _mock_stage2_hallucination(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
    ) -> Stage2LangflowResult:
        """AI 총괄 Langflow 연동 전 placeholder."""

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


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", text)
    cleaned = re.sub(r"[#*_>`]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
