"""Tests for Stage 2 Langflow client contract extension (step 8)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.clients.langflow_client import (
    LangflowClient,
    build_stage2_langflow_tweaks,
    serialize_stage2_retrieval_input,
)
from app.core.exceptions import Stage2LangflowServiceUnavailableError
from app.schemas.stage2_generation import Stage2RetrievalCandidate, Stage2RetrievalInput
from app.services.stage2_retrieval_input import build_stage2_retrieval_input


def test_serialize_stage2_retrieval_input_roundtrip() -> None:
    retrieval_input = build_stage2_retrieval_input(
        document_text="장영실은 자격루와 측우기를 발명했습니다.",
        question="발명품을 설명해줘.",
    )

    encoded = serialize_stage2_retrieval_input(retrieval_input)
    decoded = json.loads(encoded)

    assert decoded["strategy"] == "SAME_DOCUMENT_THEN_SYNTHETIC"
    assert decoded["synthetic_fallback_allowed"] is True
    assert isinstance(decoded["candidate_chunks"], list)


def test_build_stage2_langflow_tweaks_includes_planner_fields() -> None:
    retrieval_input = Stage2RetrievalInput(
        candidate_chunks=[
            Stage2RetrievalCandidate(
                chunk_id="chunk-1",
                source_index=0,
                text="동일 PDF의 혼동 가능한 청크입니다.",
                relevance_score=0.91,
                selection_bucket="TOP_RELEVANCE",
            )
        ],
    )

    tweaks = build_stage2_langflow_tweaks(
        gen_prompt_node_id="Prompt-fwk9l",
        planner_prompt_node_id="Prompt-We0Ob",
        document_text="문서 본문",
        question="질문",
        persona="페르소나",
        hallucination_types=["RETRIEVAL_ERROR", "PERSONA_BIAS"],
        expected_error_count=2,
        retrieval_input=retrieval_input,
        validation_feedback="ERROR_SENTENCE_NOT_FOUND",
    )

    gen_tweak = tweaks["Prompt-fwk9l"]
    planner_tweak = tweaks["Prompt-We0Ob"]

    assert gen_tweak["question"] == "질문"
    assert gen_tweak["persona"] == "페르소나"
    assert gen_tweak["expected_error_count"] == "2"
    assert "candidate_chunks" not in gen_tweak

    assert planner_tweak["question"] == "질문"
    assert planner_tweak["persona"] == "페르소나"
    assert planner_tweak["validation_feedback"] == "ERROR_SENTENCE_NOT_FOUND"

    candidate_payload = json.loads(planner_tweak["candidate_chunks"])
    assert candidate_payload["candidate_chunks"][0]["chunk_id"] == "chunk-1"


def test_build_stage2_langflow_tweaks_defaults_empty_retrieval() -> None:
    tweaks = build_stage2_langflow_tweaks(
        gen_prompt_node_id="Prompt-fwk9l",
        planner_prompt_node_id="Prompt-We0Ob",
        document_text="문서",
        question="질문",
        persona="페르소나",
        hallucination_types=["PERSONA_BIAS"],
        expected_error_count=1,
    )

    candidate_payload = json.loads(tweaks["Prompt-We0Ob"]["candidate_chunks"])
    assert candidate_payload["candidate_chunks"] == []
    assert tweaks["Prompt-We0Ob"]["validation_feedback"] == ""


def test_parse_stage2_outputs_rejects_invalid_errors_json() -> None:
    client = LangflowClient()
    api_response = {
        "outputs": [
            {
                "outputs": [
                    {"results": {"message": {"text": "학생용 답변"}}},
                    {"results": {"message": {"text": "not-json"}}},
                ]
            }
        ]
    }

    with pytest.raises(Stage2LangflowServiceUnavailableError):
        client._parse_stage2_outputs(api_response)


def test_parse_stage2_outputs_preserves_retrieval_metadata() -> None:
    client = LangflowClient()
    flawed = "자격루는 서양에서 온 기계입니다."
    errors_json = json.dumps(
        {
            "generated_errors": [
                {
                    "error_sentence": "자격루는 서양에서 온 기계입니다.",
                    "error_type": "RETRIEVAL_ERROR",
                    "correct_sentence": "자격루는 조선의 독자적 발명입니다.",
                    "hallucination_reason": "잘못된 검색 결과를 근거로 서술",
                    "evidence_sentence": "자격루는 물의 흐름을 이용한 자동 물시계입니다.",
                    "retrieval_source": "SAME_DOCUMENT",
                    "retrieved_context": "동일 PDF의 혼동 가능한 청크입니다.",
                }
            ]
        },
        ensure_ascii=False,
    )
    api_response = {
        "outputs": [
            {
                "outputs": [
                    {"results": {"message": {"text": flawed}}},
                    {"results": {"message": {"text": errors_json}}},
                ]
            }
        ]
    }

    parsed = client._parse_stage2_outputs(api_response)

    assert parsed.generated_errors[0].retrieval_source == "SAME_DOCUMENT"
    assert parsed.generated_errors[0].retrieved_context == "동일 PDF의 혼동 가능한 청크입니다."


@pytest.mark.asyncio
async def test_run_stage2_http_sends_extended_tweaks() -> None:
    retrieval_input = build_stage2_retrieval_input(
        document_text="장영실은 자격루와 측우기를 발명했습니다.",
        question="발명품을 설명해줘.",
    )
    api_response: dict[str, Any] = {
        "outputs": [
            {
                "outputs": [
                    {"results": {"message": {"text": "학생용 답변"}}},
                    {
                        "results": {
                            "message": {
                                "text": json.dumps(
                                    {
                                        "generated_errors": [
                                            {
                                                "error_sentence": "오류 문장",
                                                "error_type": "PERSONA_BIAS",
                                                "correct_sentence": "정답 문장",
                                                "hallucination_reason": "이유",
                                                "evidence_sentence": "근거 문장",
                                            }
                                        ]
                                    },
                                    ensure_ascii=False,
                                )
                            }
                        }
                    },
                ]
            }
        ]
    }

    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=api_response)

    mock_client = MagicMock()
    mock_client.post = AsyncMock(return_value=mock_response)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    with (
        patch("app.clients.langflow_client.settings.LANGFLOW_STAGE2_FLOW_ID", "flow-id"),
        patch(
            "app.clients.langflow_client.settings.LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID",
            "Prompt-fwk9l",
        ),
        patch(
            "app.clients.langflow_client.settings.LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID",
            "Prompt-We0Ob",
        ),
        patch("app.clients.langflow_client.httpx.AsyncClient", return_value=mock_client),
    ):
        client = LangflowClient()
        result = await client.run_stage2_hallucination(
            document_text="문서",
            question="질문",
            persona="페르소나",
            hallucination_types=["PERSONA_BIAS"],
            expected_error_count=1,
            retrieval_input=retrieval_input,
            validation_feedback="ERROR_COUNT_MISMATCH",
        )

    assert result.flawed_ai_response == "학생용 답변"
    assert len(result.generated_errors) == 1

    call_kwargs = mock_client.post.call_args.kwargs
    payload = call_kwargs["json"]
    planner_tweak = payload["tweaks"]["Prompt-We0Ob"]

    assert planner_tweak["validation_feedback"] == "ERROR_COUNT_MISMATCH"
    assert json.loads(planner_tweak["candidate_chunks"])["strategy"] == (
        "SAME_DOCUMENT_THEN_SYNTHETIC"
    )
