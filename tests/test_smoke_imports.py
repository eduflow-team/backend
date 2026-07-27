"""Smoke tests: ensure Stage 2 pipeline modules import without side effects."""


def test_import_langflow_client() -> None:
    from app.clients.langflow_client import LangflowClient, Stage2LangflowResult

    assert LangflowClient is not None
    assert Stage2LangflowResult is not None


def test_import_stage2_schemas() -> None:
    from app.schemas.stage2 import (
        ALLOWED_HALLUCINATION_TYPES,
        Stage2CreateResponse,
        Stage2GeneratedErrorItem,
    )
    from app.schemas.stage2_generation import Stage2LangflowGenerationResult

    assert "PERSONA_BIAS" in ALLOWED_HALLUCINATION_TYPES
    assert Stage2CreateResponse is not None
    assert Stage2GeneratedErrorItem is not None
    assert Stage2LangflowGenerationResult is not None


def test_import_stage2_service() -> None:
    from app.services.stage2_service import Stage2Service

    assert Stage2Service is not None


def test_import_stage2_generation_validator() -> None:
    from app.services.stage2_generation_validator import (
        Stage2GenerationValidationCode,
        validate_stage2_generation_result,
    )

    assert Stage2GenerationValidationCode.ERROR_COUNT_MISMATCH
    assert validate_stage2_generation_result is not None


def test_import_highlight_grader() -> None:
    from app.services.grading.highlight_grader import HighlightGrader

    assert HighlightGrader is not None


def test_import_geval_service() -> None:
    from app.services.grading.geval_service import GEvalService

    assert GEvalService is not None
