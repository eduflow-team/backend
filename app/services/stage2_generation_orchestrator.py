"""Stage 2 Langflow 생성 파이프라인 오케스트레이터."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass

from app.clients.langflow_client import LangflowClient
from app.core.config import settings
from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.schemas.stage2_generation import (
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
)
from app.services.stage2_generation_validator import (
    Stage2GenerationValidationCode,
    Stage2GenerationValidationResult,
    validate_stage2_generation_result,
)
from app.services.stage2_index_calculator import (
    Stage2IndexApplicationResult,
    Stage2IndexCalculationCode,
    apply_server_error_indices,
)
from app.services.stage2_generation_align import align_stage2_generation_result
from app.services.stage2_document_context import Stage2DocumentContext
from app.services.stage2_generation_logging import (
    log_stage2_generation_attempt,
    log_stage2_generation_failed,
)

logger = logging.getLogger(__name__)

_FEEDBACK_HINTS: dict[str, str] = {
    "ERROR_COUNT_MISMATCH": (
        "planned_errors 개수를 expected_error_count와 정확히 맞추세요."
    ),
    "ERROR_SENTENCE_NOT_FOUND": (
        "error_sentence가 최종 답변 본문에 정확히 한 번 포함되도록 "
        "[[ERROR_N]] 슬롯을 사용하세요."
    ),
    "EVIDENCE_NOT_FOUND": (
        "evidence_sentence는 참고 문서에 실제로 존재하는 문장을 사용하세요."
    ),
    "INVALID_ERROR_TYPE": (
        "error_type은 교사가 선택한 hallucination_types만 사용하세요."
    ),
    "ERROR_TYPE_COVERAGE_MISMATCH": (
        "오류 개수가 허용 유형 수 이상이면 선택한 각 error_type을 최소 한 번 사용하세요."
    ),
    "DUPLICATED_ERROR": (
        "서로 다른 error_sentence를 사용하고 중복 오류를 만들지 마세요."
    ),
    "RETRIEVAL_CONTEXT_MISSING": (
        "RETRIEVAL_ERROR는 retrieved_context와 retrieval_source를 포함하세요."
    ),
    "ERROR_SENTENCE_AMBIGUOUS": (
        "error_sentence가 답변 본문에서 한 번만 등장하도록 문장을 단순화하세요."
    ),
    "SLOT_MARKER_REMAINING": (
        "[[ERROR_N]] 슬롯을 정확히 한 번씩 사용하고 다른 슬롯 표기를 남기지 마세요."
    ),
    "ANSWER_LEAKAGE_DETECTED": (
        "학생용 답변에서 오류임을 밝히거나 정답을 암시하는 설명을 제거하세요."
    ),
    "CORRECT_ANSWER_EXPOSED": (
        "오류에 대응하는 correct_sentence를 학생용 답변의 정상 문장으로 노출하지 마세요."
    ),
    "UNLABELED_ERROR_DUPLICATE": (
        "각 계획 오류는 해당 슬롯에서만 한 번 말하고 유사한 오류 문장을 추가하지 마세요."
    ),
}


def build_stage2_validation_feedback(
    *,
    validation_codes: tuple[Stage2GenerationValidationCode, ...],
    index_codes: tuple[Stage2IndexCalculationCode, ...],
) -> str:
    """Langflow Planner 재시도용 검증 피드백 문자열."""
    merged_codes = tuple(
        dict.fromkeys([*validation_codes, *index_codes]),
    )
    if not merged_codes:
        return ""

    lines: list[str] = []
    for code in merged_codes:
        hint = _FEEDBACK_HINTS.get(str(code), "")
        lines.append(f"- {code}: {hint}" if hint else f"- {code}")
    return "\n".join(lines)


@dataclass(frozen=True)
class Stage2GenerationPipelineResult:
    """청크 후보 → Langflow → 검증 → 인덱스 계산 결과."""

    result: Stage2LangflowGenerationResult
    retrieval_input: Stage2RetrievalInput
    validation: Stage2GenerationValidationResult
    index_application: Stage2IndexApplicationResult
    generation_attempts: int = 1
    document_context: Stage2DocumentContext | None = None

    @property
    def candidate_chunk_ids(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.retrieval_input.candidate_chunks]

    @property
    def failure_codes(self) -> tuple[str, ...]:
        return tuple(
            dict.fromkeys(
                [
                    *[str(code) for code in self.validation.codes],
                    *[str(code) for code in self.index_application.codes],
                ]
            )
        )

    @property
    def is_ready_for_save(self) -> bool:
        return self.validation.is_valid and self.index_application.applied


class Stage2GenerationOrchestrator:
    """Stage 2 과제 생성용 Langflow 파이프라인."""

    def __init__(self, langflow_client: LangflowClient | None = None) -> None:
        self.langflow_client = langflow_client or LangflowClient()

    async def generate(
        self,
        *,
        document_text: str,
        question: str,
        persona: str,
        hallucination_types: list[str],
        expected_error_count: int,
        teacher_user_id: int | None = None,
        retrieval_input: Stage2RetrievalInput | None = None,
        document_context: Stage2DocumentContext | None = None,
    ) -> Stage2GenerationPipelineResult:
        resolved_retrieval_input = retrieval_input or build_stage2_retrieval_input(
            document_text=document_text,
            question=question,
        )
        max_attempts = settings.STAGE2_GENERATION_MAX_ATTEMPTS
        validation_feedback = ""
        last_failure_codes: tuple[str, ...] = ()

        for attempt in range(1, max_attempts + 1):
            started_at = time.perf_counter()
            try:
                langflow_result = await self.langflow_client.run_stage2_hallucination(
                    document_text=document_text,
                    question=question,
                    persona=persona,
                    hallucination_types=hallucination_types,
                    expected_error_count=expected_error_count,
                    retrieval_input=resolved_retrieval_input,
                    validation_feedback=validation_feedback,
                )
            except Stage2LangflowServiceUnavailableError:
                log_stage2_generation_failed(
                    teacher_user_id=teacher_user_id,
                    generation_attempts=attempt,
                    failure_codes=("LANGFLOW_UNAVAILABLE",),
                )
                raise
            duration_ms = (time.perf_counter() - started_at) * 1000
            aligned_result = align_stage2_generation_result(
                langflow_result,
                document_text=document_text,
                hallucination_types=hallucination_types,
                expected_error_count=expected_error_count,
            )
            validation = validate_stage2_generation_result(
                result=aligned_result,
                document_text=document_text,
                hallucination_types=hallucination_types,
                expected_error_count=expected_error_count,
            )
            index_application = apply_server_error_indices(aligned_result)
            final_result = (
                index_application.result
                if index_application.applied
                else aligned_result
            )
            pipeline = Stage2GenerationPipelineResult(
                result=final_result,
                retrieval_input=resolved_retrieval_input,
                validation=validation,
                index_application=index_application,
                generation_attempts=attempt,
                document_context=document_context,
            )
            if pipeline.is_ready_for_save:
                log_stage2_generation_attempt(
                    teacher_user_id=teacher_user_id,
                    attempt=attempt,
                    max_attempts=max_attempts,
                    duration_ms=duration_ms,
                    failure_codes=(),
                    will_retry=False,
                )
                return pipeline

            last_failure_codes = pipeline.failure_codes
            will_retry = attempt < max_attempts
            log_stage2_generation_attempt(
                teacher_user_id=teacher_user_id,
                attempt=attempt,
                max_attempts=max_attempts,
                duration_ms=duration_ms,
                failure_codes=last_failure_codes,
                will_retry=will_retry,
            )

            if will_retry:
                validation_feedback = build_stage2_validation_feedback(
                    validation_codes=validation.codes,
                    index_codes=index_application.codes,
                )

        log_stage2_generation_failed(
            teacher_user_id=teacher_user_id,
            generation_attempts=max_attempts,
            failure_codes=last_failure_codes,
        )
        raise Stage2LangflowServiceUnavailableError()
