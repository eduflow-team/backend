"""Tests for Stage 2 Langflow baseline fixture and client parsing."""

from __future__ import annotations

import json
from typing import Any

from app.clients.langflow_client import LangflowClient, Stage2LangflowResult
from app.schemas.stage2 import ALLOWED_HALLUCINATION_TYPES


def _build_langflow_api_response(
    flawed_ai_response: str,
    generated_errors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Minimal Langflow run response shape consumed by LangflowClient._parse_stage2_outputs."""
    errors_json = json.dumps({"generated_errors": generated_errors}, ensure_ascii=False)
    return {
        "outputs": [
            {
                "outputs": [
                    {
                        "results": {
                            "message": {"text": flawed_ai_response},
                        }
                    },
                    {
                        "results": {
                            "message": {"text": errors_json},
                        }
                    },
                ]
            }
        ]
    }


def test_stage2_langflow_fixture_loads(stage2_langflow_baseline_fixture: dict[str, Any]) -> None:
    assert stage2_langflow_baseline_fixture["meta"]["case_id"] == "jangyeongsil-baseline"
    assert "input" in stage2_langflow_baseline_fixture
    assert "langflow_result" in stage2_langflow_baseline_fixture


def test_stage2_langflow_fixture_input(stage2_langflow_baseline_fixture: dict[str, Any]) -> None:
    inp = stage2_langflow_baseline_fixture["input"]
    assert inp["expected_error_count"] == 2
    assert set(inp["hallucination_types"]) <= ALLOWED_HALLUCINATION_TYPES
    assert inp["document_text"]
    assert inp["question"]
    assert inp["persona"]


def test_stage2_langflow_fixture_output_structure(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    inp = stage2_langflow_baseline_fixture["input"]
    result = stage2_langflow_baseline_fixture["langflow_result"]
    flawed = result["flawed_ai_response"]
    errors = result["generated_errors"]

    assert len(errors) == inp["expected_error_count"]
    required_keys = {
        "error_sentence",
        "error_type",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
    }
    for err in errors:
        assert required_keys <= set(err.keys())
        assert err["error_type"] in ALLOWED_HALLUCINATION_TYPES
        assert err["error_sentence"] in flawed


def test_langflow_client_parses_baseline_fixture(
    stage2_langflow_baseline_fixture: dict[str, Any],
) -> None:
    result_data = stage2_langflow_baseline_fixture["langflow_result"]
    api_response = _build_langflow_api_response(
        result_data["flawed_ai_response"],
        result_data["generated_errors"],
    )

    client = LangflowClient()
    parsed: Stage2LangflowResult = client._parse_stage2_outputs(api_response)

    assert parsed.flawed_ai_response == result_data["flawed_ai_response"]
    assert len(parsed.generated_errors) == len(result_data["generated_errors"])
    assert parsed.generated_errors[0]["error_type"] == "RETRIEVAL_ERROR"
    assert parsed.generated_errors[1]["error_type"] == "PERSONA_BIAS"
