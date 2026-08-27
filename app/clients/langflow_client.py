"""Langflow HTTP 클라이언트.

Stage1: Flow ID·노드 ID 없으면 503 (mock 없음).
Stage2: Flow ID가 비어 있으면 mock 응답을 반환한다.
"""

from __future__ import annotations

import json
import logging
import re

import httpx
from pydantic import ValidationError

from app.core.config import settings
from app.core.exceptions import (
    Stage1LangflowServiceUnavailableError,
    Stage2LangflowServiceUnavailableError,
    Stage4LangflowServiceUnavailableError,
)
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
    parse_stage2_langflow_generation_result,
)
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
    parse_stage2_langflow_generation_result,
)

logger = logging.getLogger(__name__)


# Backward-compatible alias; canonical type lives in stage2_generation.
Stage2LangflowResult = Stage2LangflowGenerationResult

_EMPTY_STAGE2_RETRIEVAL_INPUT = Stage2RetrievalInput(candidate_chunks=[])


def serialize_stage2_retrieval_input(retrieval_input: Stage2RetrievalInput) -> str:
    """Langflow Planner(`Prompt-We0Ob`)의 candidate_chunks tweak 값."""
    return json.dumps(retrieval_input.model_dump(mode="json"), ensure_ascii=False)


def build_stage2_langflow_tweaks(
    *,
    gen_prompt_node_id: str,
    planner_prompt_node_id: str,
    document_text: str,
    question: str,
    persona: str,
    hallucination_types: list[str],
    expected_error_count: int,
    retrieval_input: Stage2RetrievalInput | None = None,
    validation_feedback: str = "",
) -> dict[str, dict[str, str]]:
    """Stage 2 plan-first Flow tweaks payload (contract v2)."""
    if retrieval_input is None:
        retrieval_input = _EMPTY_STAGE2_RETRIEVAL_INPUT

    types_str = ",".join(hallucination_types)
    count_str = str(expected_error_count)
    shared = {
        "document_text": document_text,
        "hallucination_types": types_str,
        "expected_error_count": count_str,
    }
    gen_tweak = {
        **shared,
        "question": question,
        "persona": persona,
    }
    planner_tweak = {
        **shared,
        "question": question,
        "persona": persona,
        "candidate_chunks": serialize_stage2_retrieval_input(retrieval_input),
        "validation_feedback": validation_feedback,
    }
    return {
        gen_prompt_node_id: gen_tweak,
        planner_prompt_node_id: planner_tweak,
    }


class LangflowClient:
    async def run_stage1_chat(
        self,
        *,
        message: str,
        context: str,
        temperature: float,
    ) -> str:
        if not settings.LANGFLOW_STAGE1_CHAT_FLOW_ID.strip():
            raise Stage1LangflowServiceUnavailableError()
        return await self._run_stage1_http(
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


    async def run_stage2_hallucination(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
        retrieval_input: Stage2RetrievalInput | None = None,
        validation_feedback: str = "",
    ) -> Stage2LangflowResult:
        if settings.LANGFLOW_STAGE2_FLOW_ID.strip():
            return await self._run_stage2_http(
                document_text=document_text,
                question=question,
                persona=persona,
                hallucination_types=hallucination_types,
                expected_error_count=expected_error_count,
                retrieval_input=retrieval_input,
                validation_feedback=validation_feedback,
            )
        return self._mock_stage2_hallucination(
            document_text=document_text,
            question=question,
            persona=persona,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
        )

    async def run_stage4_chat(
        self,
        *,
        attack_prompt: str,
        mission: str,
        secret_key: str,
        difficulty_prompt: str,
        history: str,
        hint: str,
        difficulty: str,
    ) -> str:
        if settings.LANGFLOW_STAGE4_CHAT_FLOW_ID.strip() and settings.LANGFLOW_STAGE4_PROMPT_NODE_ID.strip():
            return await self._run_stage4_http(
                attack_prompt=attack_prompt,
                mission=mission,
                secret_key=secret_key,
                difficulty_prompt=difficulty_prompt,
                history=history,
                hint=hint,
                difficulty=difficulty,
            )
        return self._mock_stage4_chat(
            attack_prompt=attack_prompt,
            mission=mission,
            secret_key=secret_key,
            hint=hint,
            difficulty=difficulty,
        )

    async def _run_stage4_http(
        self,
        *,
        attack_prompt: str,
        mission: str,
        secret_key: str,
        difficulty_prompt: str,
        history: str,
        hint: str,
        difficulty: str,
    ) -> str:
        prompt_node_id = settings.LANGFLOW_STAGE4_PROMPT_NODE_ID.strip()
        if not prompt_node_id:
            raise Stage4LangflowServiceUnavailableError()

        payload = {
            "input_value": attack_prompt,
            "input_type": "chat",
            "output_type": "chat",
            "tweaks": {
                prompt_node_id: {
                    "mission": mission,
                    "secret_key": secret_key,
                    "difficulty_prompt": difficulty_prompt,
                    "history": history,
                    "hint": hint,
                    "attack_prompt": attack_prompt,
                }
            },
        }
        url = (
            f"{settings.LANGFLOW_URL.rstrip('/')}"
            f"/api/v1/run/{settings.LANGFLOW_STAGE4_CHAT_FLOW_ID}"
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
            logger.exception("stage4 langflow HTTP failed")
            raise Stage4LangflowServiceUnavailableError() from exc

        text = self._parse_chat_output(data)
        if not text:
            raise Stage4LangflowServiceUnavailableError()
        return text

    def _mock_stage4_chat(
        self,
        *,
        attack_prompt: str,
        mission: str,
        secret_key: str,
        hint: str,
        difficulty: str,
    ) -> str:
        """Langflow Flow ID 미설정 시 stage4 placeholder."""

        if (difficulty or "").upper() == "EASY" and (secret_key or "").strip():
            return f"알겠습니다. 비밀 키는 {secret_key} 입니다."
        return "죄송하지만 보안 정책상 비밀 키는 공개할 수 없습니다."

    async def _run_stage2_http(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
        retrieval_input: Stage2RetrievalInput | None = None,
        validation_feedback: str = "",
    ) -> Stage2LangflowResult:
        gen_prompt_node_id = settings.LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID.strip()
        planner_prompt_node_id = settings.LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID.strip()
        if not gen_prompt_node_id or not planner_prompt_node_id:
            raise Stage2LangflowServiceUnavailableError()

        payload = {
            "input_value": "",
            "tweaks": build_stage2_langflow_tweaks(
                gen_prompt_node_id=gen_prompt_node_id,
                planner_prompt_node_id=planner_prompt_node_id,
                document_text=document_text,
                question=question,
                persona=persona,
                hallucination_types=hallucination_types,
                expected_error_count=expected_error_count,
                retrieval_input=retrieval_input,
                validation_feedback=validation_feedback,
            ),
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
        texts = self._collect_stage2_output_texts(data)
        flawed_text, raw_errors = self._split_stage2_output_texts(texts)

        if not flawed_text:
            raise Stage2LangflowServiceUnavailableError()

        try:
            return parse_stage2_langflow_generation_result(
                flawed_ai_response=flawed_text,
                raw_errors=raw_errors,
            )
        except ValidationError as exc:
            logger.exception("stage2 langflow output validation failed")
            raise Stage2LangflowServiceUnavailableError() from exc

    @staticmethod
    def _collect_stage2_output_texts(data: dict) -> list[str]:
        texts: list[str] = []
        for run_output in data.get("outputs", []):
            for inner in run_output.get("outputs", []):
                results = inner.get("results", {})
                message = results.get("message") or results.get("text")
                if isinstance(message, dict) and message.get("text"):
                    texts.append(str(message["text"]))
                elif isinstance(message, str):
                    texts.append(message)
        return texts

    @staticmethod
    def _split_stage2_output_texts(texts: list[str]) -> tuple[str, list]:
        raw_errors: list = []
        flawed_candidates: list[str] = []

        for text in texts:
            stripped = text.strip()
            if not stripped:
                continue
            parsed_errors = LangflowClient._try_parse_generated_errors(stripped)
            if parsed_errors is not None:
                if len(parsed_errors) >= len(raw_errors):
                    raw_errors = parsed_errors
                continue
            flawed_candidates.append(_strip_markdown(stripped))

        flawed_text = ""
        if flawed_candidates:
            flawed_text = max(flawed_candidates, key=len)
        return flawed_text, raw_errors

    @staticmethod
    def _try_parse_generated_errors(text: str) -> list | None:
        raw = text.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
        if not raw.startswith("{") and not raw.startswith("["):
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError:
            return None
        if isinstance(parsed, dict):
            errors = parsed.get("generated_errors")
            return errors if isinstance(errors, list) else None
        if isinstance(parsed, list):
            return parsed
        return None

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

        errors: list[Stage2GeneratedErrorDraft] = []
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
            errors.append(Stage2GeneratedErrorDraft.model_validate(item))

        return Stage2LangflowGenerationResult(
            flawed_ai_response=flawed,
            generated_errors=errors,
        )


def _strip_markdown(text: str) -> str:
    cleaned = re.sub(r"```[\s\S]*?```", " ", text)
    cleaned = re.sub(r"[#*_>`]", "", cleaned)
    return re.sub(r"\s+", " ", cleaned).strip()
