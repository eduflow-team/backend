"""Tests for Stage 2 generation metadata schema and model wiring."""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from app.models.stage import Stage2AssignmentDetail
from app.repositories.stage import Stage2DetailRepository
from app.schemas.stage2_generation import (
    Stage2GenerationMetadata,
    dump_stage2_generation_metadata,
    parse_stage2_generation_metadata,
)


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
