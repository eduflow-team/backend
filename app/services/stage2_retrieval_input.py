"""Stage 2 Langflow Retrieval 후보 입력 구성."""

from __future__ import annotations

from app.schemas.stage2_generation import (
    Stage2RetrievalCandidate,
    Stage2RetrievalInput,
)
from app.services.stage2_chunk_candidates import (
    Stage2ChunkCandidate,
    build_stage2_chunk_candidates,
)


def build_stage2_retrieval_input(
    *,
    document_text: str,
    question: str,
) -> Stage2RetrievalInput:
    """동일 PDF 후보를 우선 제공하고 synthetic fallback 정책을 명시한다."""
    candidates = build_stage2_chunk_candidates(
        document_text=document_text,
        question=question,
    )
    return build_stage2_retrieval_input_from_candidates(candidates)


def build_stage2_retrieval_input_from_candidates(
    candidates: list[Stage2ChunkCandidate],
) -> Stage2RetrievalInput:
    """생성된 내부 후보를 Langflow 입력 스키마로 변환한다."""
    return Stage2RetrievalInput(
        candidate_chunks=[
            Stage2RetrievalCandidate(
                chunk_id=candidate.chunk_id,
                source_index=candidate.source_index,
                text=candidate.text,
                relevance_score=candidate.relevance_score,
                selection_bucket=candidate.selection_bucket,
            )
            for candidate in candidates
        ],
    )
