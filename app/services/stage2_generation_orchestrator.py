"""Stage 2 Langflow 생성 파이프라인 오케스트레이터."""

from __future__ import annotations

from dataclasses import dataclass

from app.clients.langflow_client import LangflowClient
from app.schemas.stage2_generation import (
    Stage2LangflowGenerationResult,
    Stage2RetrievalInput,
)
from app.services.stage2_generation_validator import (
    Stage2GenerationValidationResult,
    validate_stage2_generation_result,
)
from app.services.stage2_index_calculator import (
    Stage2IndexApplicationResult,
    apply_server_error_indices,
)
from app.services.stage2_retrieval_input import build_stage2_retrieval_input


@dataclass(frozen=True)
class Stage2GenerationPipelineResult:
    """청크 후보 → Langflow → 검증 → 인덱스 계산 결과."""

    result: Stage2LangflowGenerationResult
    retrieval_input: Stage2RetrievalInput
    validation: Stage2GenerationValidationResult
    index_application: Stage2IndexApplicationResult
    generation_attempts: int = 1

    @property
    def candidate_chunk_ids(self) -> list[str]:
        return [chunk.chunk_id for chunk in self.retrieval_input.candidate_chunks]

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
        validation_feedback: str = "",
        generation_attempts: int = 1,
    ) -> Stage2GenerationPipelineResult:
        retrieval_input = build_stage2_retrieval_input(
            document_text=document_text,
            question=question,
        )
        langflow_result = await self.langflow_client.run_stage2_hallucination(
            document_text=document_text,
            question=question,
            persona=persona,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
            retrieval_input=retrieval_input,
            validation_feedback=validation_feedback,
        )
        validation = validate_stage2_generation_result(
            result=langflow_result,
            document_text=document_text,
            hallucination_types=hallucination_types,
            expected_error_count=expected_error_count,
        )
        index_application = apply_server_error_indices(langflow_result)
        final_result = (
            index_application.result
            if index_application.applied
            else langflow_result
        )
        return Stage2GenerationPipelineResult(
            result=final_result,
            retrieval_input=retrieval_input,
            validation=validation,
            index_application=index_application,
            generation_attempts=generation_attempts,
        )
