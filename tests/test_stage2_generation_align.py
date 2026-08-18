"""Tests for Stage 2 generation alignment."""

from __future__ import annotations

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.stage2_generation_align import align_stage2_generation_result


def _error(error_type: str) -> Stage2GeneratedErrorDraft:
    return Stage2GeneratedErrorDraft(
        error_sentence=f"{error_type} sentence",
        error_type=error_type,
        correct_sentence="correct",
        hallucination_reason="reason",
        evidence_sentence="evidence",
    )


def test_align_trims_extra_errors() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="answer",
        generated_errors=[
            _error("PERSONA_BIAS"),
            _error("INFORMATION_FABRICATION"),
            _error("RETRIEVAL_ERROR"),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS", "INFORMATION_FABRICATION"],
        expected_error_count=2,
    )

    assert len(aligned.generated_errors) == 2
    assert aligned.generated_errors[0].error_type == "PERSONA_BIAS"
    assert aligned.generated_errors[1].error_type == "INFORMATION_FABRICATION"


def test_align_remaps_error_types_in_request_order() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="answer",
        generated_errors=[
            _error("RETRIEVAL_ERROR"),
            _error("PERSONA_BIAS"),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS", "INFORMATION_FABRICATION"],
        expected_error_count=2,
    )

    assert aligned.generated_errors[0].error_type == "PERSONA_BIAS"
    assert aligned.generated_errors[1].error_type == "INFORMATION_FABRICATION"


def test_align_sanitizes_slot_markers_and_meta_lines() -> None:
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=(
            "도입 문장.\n"
            "정상 설명: 메타 라벨.\n"
            "[[ERROR_1]]\n"
            "사실과 다릅니다."
        ),
        generated_errors=[
            Stage2GeneratedErrorDraft(
                error_sentence="틀린 문장입니다.",
                error_type="PERSONA_BIAS",
                correct_sentence="correct",
                hallucination_reason="reason",
                evidence_sentence="evidence",
            ),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS"],
        expected_error_count=1,
    )

    assert "[[ERROR_1]]" not in aligned.flawed_ai_response
    assert "정상 설명" not in aligned.flawed_ai_response
    assert "사실과 다릅니다" not in aligned.flawed_ai_response
    assert "틀린 문장입니다." in aligned.flawed_ai_response


def test_align_snaps_evidence_to_document_with_pdf_line_break() -> None:
    document_text = (
        "⑤ 송, 원 등은 취안저우 등 무역항에 시박사\n"
        "를 설치하여 무역을 관리하였다."
    )
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="answer",
        generated_errors=[
            Stage2GeneratedErrorDraft(
                error_sentence="error",
                error_type="PERSONA_BIAS",
                correct_sentence="correct",
                hallucination_reason="reason",
                evidence_sentence=(
                    "송, 원 등은 취안저우 등 무역항에 시박사를 설치하여 무역을 관리하였다."
                ),
            ),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        document_text=document_text,
        hallucination_types=["PERSONA_BIAS"],
        expected_error_count=1,
    )

    assert "\n" in aligned.generated_errors[0].evidence_sentence
    assert "시박사" in aligned.generated_errors[0].evidence_sentence


def test_align_dedupes_repeated_error_sentences() -> None:
    sentence = "청과의 교역은 모범 사례였다."
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=f"도입. {sentence} 중간. {sentence} 마무리.",
        generated_errors=[
            Stage2GeneratedErrorDraft(
                error_sentence=sentence,
                error_type="PERSONA_BIAS",
                correct_sentence="correct",
                hallucination_reason="reason",
                evidence_sentence="evidence",
            ),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["PERSONA_BIAS"],
        expected_error_count=1,
    )

    assert aligned.flawed_ai_response.count(sentence) == 1


def test_align_repairs_fake_evidence_from_candidate_chunks() -> None:
    document_text = (
        "⑤ 송, 원 등은 취안저우 등 무역항에 시박사\n"
        "를 설치하여 무역을 관리하였다."
    )
    candidate_chunks = [
        "장영실은 자격루와 측우기를 발명한 과학자이다. "
        "자격루는 물의 흐름을 이용한 물시계이다.",
    ]
    result = Stage2LangflowGenerationResult(
        flawed_ai_response="장영실은 연을 발명했다.",
        generated_errors=[
            Stage2GeneratedErrorDraft(
                error_sentence="장영실은 연을 발명했다.",
                error_type="INFORMATION_FABRICATION",
                correct_sentence="자격루는 물의 흐름을 이용한 물시계이다.",
                hallucination_reason="문서에 연 발명 근거가 없다.",
                evidence_sentence="본문 16쪽",
            ),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        document_text=document_text,
        candidate_chunk_texts=candidate_chunks,
        hallucination_types=["INFORMATION_FABRICATION"],
        expected_error_count=1,
    )

    evidence = aligned.generated_errors[0].evidence_sentence
    assert "본문 16쪽" not in evidence
    assert "자격루" in evidence or "물시계" in evidence


def test_align_strips_exposed_correct_sentence() -> None:
    correct = "자격루는 물의 흐름을 이용한 물시계이다."
    error = "장영실은 연을 발명했다."
    result = Stage2LangflowGenerationResult(
        flawed_ai_response=f"도입. {error} {correct}",
        generated_errors=[
            Stage2GeneratedErrorDraft(
                error_sentence=error,
                error_type="INFORMATION_FABRICATION",
                correct_sentence=correct,
                hallucination_reason="reason",
                evidence_sentence="evidence",
            ),
        ],
    )

    aligned = align_stage2_generation_result(
        result,
        hallucination_types=["INFORMATION_FABRICATION"],
        expected_error_count=1,
    )

    assert correct not in aligned.flawed_ai_response
    assert error in aligned.flawed_ai_response
