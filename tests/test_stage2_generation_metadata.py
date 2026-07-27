"""Tests for Stage 2 generation metadata schema and model wiring."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.stage import Stage2AssignmentDetail
from app.repositories.stage import Stage2DetailRepository
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2GenerationMetadata,
    Stage2LangflowGenerationResult,
    Stage2RetrievalCandidate,
    Stage2RetrievalInput,
    dump_stage2_generation_metadata,
    parse_stage2_generation_metadata,
)
from app.services.stage2_generation_metadata import build_stage2_generation_metadata
from app.services.stage2_generation_orchestrator import Stage2GenerationPipelineResult
from app.services.stage2_generation_validator import Stage2GenerationValidationResult
from app.services.stage2_index_calculator import Stage2IndexApplicationResult


def test_generation_metadata_roundtrip() -> None:
    metadata = Stage2GenerationMetadata(
        flow_version="stage2-v2",
        generation_attempts=2,
        retrieval_source="SAME_DOCUMENT",
        retrieved_context="동일 PDF distractor 청크",
        validation_codes=["ERROR_COUNT_MISMATCH"],
        candidate_chunk_ids=["chunk-0", "chunk-3"],
    )

    dumped = dump_stage2_generation_metadata(metadata)
    restored = parse_stage2_generation_metadata(dumped)

    assert restored == metadata
    assert json.loads(json.dumps(dumped, ensure_ascii=False)) == dumped


def test_generation_metadata_rejects_invalid_retrieval_source() -> None:
    with pytest.raises(ValidationError):
        Stage2GenerationMetadata(
            flow_version="stage2-v2",
            generation_attempts=1,
            retrieval_source="INVALID",
        )


def test_generation_metadata_rejects_zero_attempts() -> None:
    with pytest.raises(ValidationError):
        Stage2GenerationMetadata(
            flow_version="stage2-v2",
            generation_attempts=0,
        )


def test_parse_none_metadata_returns_none() -> None:
    assert parse_stage2_generation_metadata(None) is None


def test_stage2_detail_model_has_generation_metadata_column() -> None:
    assert "generation_metadata" in Stage2AssignmentDetail.__table__.c


def test_stage2_detail_repository_exposes_set_generation_metadata() -> None:
    assert hasattr(Stage2DetailRepository, "set_generation_metadata")


def test_build_generation_metadata_from_ready_pipeline() -> None:
    flawed = (
        "장영실은 정말 뛰어난 발명가였어요. "
        "특히 자격루는 사실 서양에서 온 기계라고 알려져 있어요."
    )
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=flawed,
        generated_errors=[
            Stage2GeneratedErrorDraft.model_validate(
                {
                    "error_sentence": "특히 자격루는 사실 서양에서 온 기계라고 알려져 있어요.",
                    "error_type": "RETRIEVAL_ERROR",
                    "correct_sentence": "자격루는 조선의 독자적 발명입니다.",
                    "hallucination_reason": "잘못된 검색 결과",
                    "evidence_sentence": "장영실은 자격루와 측우기를 발명했습니다.",
                    "retrieval_source": "SAME_DOCUMENT",
                    "retrieved_context": "동일 PDF distractor 청크",
                }
            ),
            Stage2GeneratedErrorDraft.model_validate(
                {
                    "error_sentence": "하늘을 나는 연을 만들었다는 이야기도 있어요.",
                    "error_type": "PERSONA_BIAS",
                    "correct_sentence": "자격루와 측우기를 발명했습니다.",
                    "hallucination_reason": "페르소나 편향",
                    "evidence_sentence": "장영실은 자격루와 측우기를 발명했습니다.",
                }
            ),
        ],
    )
    pipeline = Stage2GenerationPipelineResult(
        result=result,
        retrieval_input=Stage2RetrievalInput(
            candidate_chunks=[
                Stage2RetrievalCandidate(
                    chunk_id="chunk-0",
                    source_index=0,
                    text="동일 PDF distractor 청크",
                    relevance_score=0.88,
                    selection_bucket="TOP_RELEVANCE",
                )
            ],
        ),
        validation=Stage2GenerationValidationResult(is_valid=True, codes=()),
        index_application=Stage2IndexApplicationResult(
            result=result,
            codes=(),
            applied=True,
        ),
        generation_attempts=2,
    )

    metadata = build_stage2_generation_metadata(pipeline)

    assert metadata == Stage2GenerationMetadata(
        flow_version="stage2-v2",
        generation_attempts=2,
        retrieval_source="SAME_DOCUMENT",
        retrieved_context="동일 PDF distractor 청크",
        validation_codes=[],
        candidate_chunk_ids=["chunk-0"],
    )

