"""Tests for G-Eval service LLM routing."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from app.services.grading.geval_service import (
    GEvalLlmConfig,
    GEvalService,
    resolve_geval_llm_config,
)


def test_resolve_geval_llm_config_uses_openai() -> None:
    with patch(
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


def test_resolve_geval_llm_config_returns_none_without_api_key() -> None:
    with patch(
        "app.services.grading.geval_service.settings.OPENAI_API_KEY",
        "",
    ):
        assert resolve_geval_llm_config() is None


@pytest.mark.asyncio
async def test_evaluate_reasoning_uses_openai() -> None:
    service = GEvalService()
    llm_config = GEvalLlmConfig(
        chat_completions_url="https://api.openai.com/v1/chat/completions",
        api_key="sk-test",
        model="gpt-4o-mini",
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


@pytest.mark.asyncio
async def test_evaluate_correction_short_circuits_exact_match() -> None:
    service = GEvalService()
    correct = "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다."

    with patch(
        "app.services.grading.geval_service.resolve_geval_llm_config",
        return_value=GEvalLlmConfig(
            chat_completions_url="https://api.openai.com/v1/chat/completions",
            api_key="sk-test",
            model="gpt-4o-mini",
        ),
    ), patch(
        "app.services.grading.geval_service._request_geval_json",
        new=AsyncMock(),
    ) as mock_request:
        result = await service.evaluate_correction(
            student_answer=correct,
            correct_sentence=correct,
            original_highlight="틀린 문장",
            reference_document="reference",
            hallucination_reason="reason",
            evidence_sentence="evidence",
        )

    assert result.factual_accuracy == 5
    assert result.completeness == 5
    mock_request.assert_not_awaited()


@pytest.mark.asyncio
async def test_evaluate_reasoning_structured_pass_meets_threshold() -> None:
    service = GEvalService()
    llm_config = GEvalLlmConfig(
        chat_completions_url="https://api.openai.com/v1/chat/completions",
        api_key="sk-test",
        model="gpt-4o-mini",
    )
    evidence = "자격루는 물의 흐름을 이용한 물시계이다."
    hallucination_reason = "문서에 연 발명 근거가 없다."
    student_reason = (
        f"참고 문서 근거 문장은 '{evidence}' 입니다. "
        f"AI 답변은 {hallucination_reason} "
        "따라서 INFORMATION_FABRICATION 유형의 환각입니다."
    )

    with patch(
        "app.services.grading.geval_service.resolve_geval_llm_config",
        return_value=llm_config,
    ), patch(
        "app.services.grading.geval_service._request_geval_json",
        new=AsyncMock(return_value={"rating": 3, "feedback": "보통입니다."}),
    ), patch(
        "app.services.grading.geval_service.settings.STAGE2_REASONING_THRESHOLD",
        0.95,
    ):
        result = await service.evaluate_reasoning(
            student_reason=student_reason,
            student_error_type="INFORMATION_FABRICATION",
            hallucination_reason=hallucination_reason,
            evidence_sentence=evidence,
            reference_document=evidence,
            location_ok=True,
            type_ok=True,
        )

    assert result.reasoning_score >= 0.95
