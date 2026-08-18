"""Tests for Stage 2 Langflow retrieval candidate input."""

from __future__ import annotations

import json

from app.schemas.stage2_generation import Stage2RetrievalInput
from app.services.stage2_chunk_candidates import Stage2ChunkCandidate
from app.services.stage2_retrieval_input import (
    build_stage2_retrieval_input,
    build_stage2_retrieval_input_from_candidates,
)


def test_build_retrieval_input_from_document() -> None:
    retrieval_input = build_stage2_retrieval_input(
        document_text=(
            "장영실은 자격루와 측우기를 발명한 과학자입니다. "
            "자격루는 물의 흐름을 이용한 자동 물시계입니다."
        ),
        question="장영실의 발명품은 무엇인가요?",
    )

    assert retrieval_input.strategy == "SAME_DOCUMENT_THEN_SYNTHETIC"
    assert retrieval_input.synthetic_fallback_allowed is True
    assert retrieval_input.candidate_chunks
    assert retrieval_input.candidate_chunks[0].chunk_id.startswith("chunk-")


def test_retrieval_input_preserves_candidate_metadata() -> None:
    candidate = Stage2ChunkCandidate(
        chunk_id="chunk-7",
        source_index=7,
        text="동일 PDF의 혼동 가능한 청크입니다.",
        relevance_score=0.42,
        selection_bucket="DIVERSE_CONTEXT",
    )

    retrieval_input = build_stage2_retrieval_input_from_candidates([candidate])
    converted = retrieval_input.candidate_chunks[0]

    assert converted.chunk_id == "chunk-7"
    assert converted.source_index == 7
    assert converted.text == candidate.text
    assert converted.relevance_score == 0.42
    assert converted.selection_bucket == "DIVERSE_CONTEXT"


def test_empty_document_keeps_synthetic_fallback() -> None:
    retrieval_input = build_stage2_retrieval_input(
        document_text="   ",
        question="질문",
    )

    assert retrieval_input.candidate_chunks == []
    assert retrieval_input.synthetic_fallback_allowed is True


def test_retrieval_input_serializes_for_langflow_payload() -> None:
    retrieval_input = build_stage2_retrieval_input(
        document_text=(
            "세종 시대의 과학 기술에 관한 충분히 긴 설명입니다. "
            "장영실과 자격루에 대한 내용을 포함합니다."
        ),
        question="자격루를 설명해줘.",
    )

    serialized = retrieval_input.model_dump(mode="json")
    encoded = json.dumps(serialized, ensure_ascii=False)
    decoded = json.loads(encoded)

    assert decoded["strategy"] == "SAME_DOCUMENT_THEN_SYNTHETIC"
    assert isinstance(decoded["candidate_chunks"], list)
    assert set(decoded["candidate_chunks"][0]) == {
        "chunk_id",
        "source_index",
        "text",
        "relevance_score",
        "selection_bucket",
    }


def test_retrieval_input_is_internal_schema() -> None:
    fields = Stage2RetrievalInput.model_fields
    assert set(fields) == {
        "strategy",
        "candidate_chunks",
        "synthetic_fallback_allowed",
    }
