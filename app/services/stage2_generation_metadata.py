"""Stage 2 생성 메타데이터 구성."""

from __future__ import annotations

from app.core.config import settings
from app.schemas.stage2_generation import Stage2GenerationMetadata
from app.services.stage2_generation_orchestrator import Stage2GenerationPipelineResult


def build_stage2_generation_metadata(
    pipeline: Stage2GenerationPipelineResult,
) -> Stage2GenerationMetadata:
    """검증 통과 pipeline에서 DB 저장용 메타데이터를 구성한다."""
    retrieval_error = next(
        (
            error
            for error in pipeline.result.generated_errors
            if error.error_type == "RETRIEVAL_ERROR"
        ),
        None,
    )
    return Stage2GenerationMetadata(
        flow_version=settings.STAGE2_FLOW_VERSION,
        generation_attempts=pipeline.generation_attempts,
        retrieval_source=(
            retrieval_error.retrieval_source if retrieval_error else None
        ),
        retrieved_context=(
            retrieval_error.retrieved_context if retrieval_error else None
        ),
        validation_codes=[],
        candidate_chunk_ids=pipeline.candidate_chunk_ids,
    )
