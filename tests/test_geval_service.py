"""Tests for G-Eval service LLM routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.grading.geval_service import (
    GEvalLlmConfig,
    GEvalService,
    resolve_geval_llm_config,
)


def test_resolve_geval_llm_config_prefers_local_endpoint() -> None:
    with patch(
        "app.services.grading.geval_service.settings.GEVAL_LLM_BASE_URL",
        "http://localhost:11434/v1",
    ), patch(
        "app.services.grading.geval_service.settings.GEVAL_LLM_MODEL",
        "exaone3.5:7.8b",
    ), patch(
        "app.services.grading.geval_service.settings.OPENAI_API_KEY",
        "sk-test",
    ):
        config = resolve_geval_llm_config()

    assert config is not None
    assert config.model == "exaone3.5:7.8b"
    assert config.chat_completions_url == "http://localhost:11434/v1/chat/completions"


def test_resolve_geval_llm_config_falls_back_to_openai() -> None:
    with patch(
        "app.services.grading.geval_service.settings.GEVAL_LLM_BASE_URL",
        "",
    ), patch(
        "app.services.grading.geval_service.settings.GEVAL_LLM_MODEL",
        "",
    ), patch(
        "app.services.grading.geval_service.settings.OPENAI_API_KEY",
        "sk-test",
    ), patch(
        "app.services.grading.geval_service.settings.OPENAI_CHAT_MODEL",
        "gpt-4o-mini",
    ):
        config = resolve_geval_llm_config()

    assert config is not None
    assert config.chat_completions_url.endswith("/v1/chat/completions")
    assert config.model == "gpt-4o-mini"


@pytest.mark.asyncio
async def test_evaluate_reasoning_uses_local_llm() -> None:
    service = GEvalService()
    llm_config = GEvalLlmConfig(
        chat_completions_url="http://localhost:11434/v1/chat/completions",
        api_key="ollama",
        model="exaone3.5:7.8b",
    )

    with patch(
        "app.services.grading.geval_service.resolve_geval_llm_config",
        return_value=llm_config,
    ), patch(
        "app.services.grading.geval_service._request_geval_json",
        new=AsyncMock(
            return_value={"rating": 5, "feedback": "근거가 타당합니다."},
        ),
    ) as mock_request:
        result = await service.evaluate_reasoning(
            student_reason="문서에 자격루는 물시계라고 나옵니다.",
            student_error_type="RETRIEVAL_ERROR",
            hallucination_reason="문서에 없는 주장",
            evidence_sentence="자격루는 물의 흐름을 이용한 물시계입니다.",
            reference_document="자격루는 물의 흐름을 이용한 물시계입니다.",
            location_ok=True,
            type_ok=True,
        )

    assert result.reasoning_score == 1.0
    assert result.ai_feedback == "근거가 타당합니다."
    mock_request.assert_awaited_once()
    assert mock_request.await_args.kwargs["llm_config"] == llm_config
