"""Stage 2 Langflow 생성 결과 품질 검증 (순수 함수)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import settings
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.grading.highlight_grader import _normalize, _overlap_score
from app.services.stage2_response_quality import (
    find_stage2_response_quality_codes,
    has_similar_response_sentence,
)


class Stage2GenerationValidationCode(StrEnum):
    ERROR_COUNT_MISMATCH = "ERROR_COUNT_MISMATCH"
    ERROR_SENTENCE_NOT_FOUND = "ERROR_SENTENCE_NOT_FOUND"
    EVIDENCE_NOT_FOUND = "EVIDENCE_NOT_FOUND"
    INVALID_ERROR_TYPE = "INVALID_ERROR_TYPE"
    ERROR_TYPE_COVERAGE_MISMATCH = "ERROR_TYPE_COVERAGE_MISMATCH"
    DUPLICATED_ERROR = "DUPLICATED_ERROR"
    RETRIEVAL_CONTEXT_MISSING = "RETRIEVAL_CONTEXT_MISSING"
    SLOT_MARKER_REMAINING = "SLOT_MARKER_REMAINING"
    ANSWER_LEAKAGE_DETECTED = "ANSWER_LEAKAGE_DETECTED"
    CORRECT_ANSWER_EXPOSED = "CORRECT_ANSWER_EXPOSED"
    UNLABELED_ERROR_DUPLICATE = "UNLABELED_ERROR_DUPLICATE"


@dataclass(frozen=True)
class Stage2GenerationValidationResult:
    is_valid: bool
    codes: tuple[Stage2GenerationValidationCode, ...]


def validate_stage2_generation_result(
    *,
    result: Stage2LangflowGenerationResult,
    document_text: str,
    hallucination_types: list[str],
    expected_error_count: int,
    evidence_match_threshold: float | None = None,
) -> Stage2GenerationValidationResult:
    """Langflow 생성 결과가 저장 가능한 품질 기준을 만족하는지 검사한다."""
    threshold = (
        settings.STAGE2_LOCATION_THRESHOLD
        if evidence_match_threshold is None
        else evidence_match_threshold
    )
    allowed_types = {value.strip().upper() for value in hallucination_types if value.strip()}
    normalized_document = _normalize(document_text)
    normalized_flawed = _normalize(result.flawed_ai_response)

    codes: list[Stage2GenerationValidationCode] = []
    codes.extend(
        Stage2GenerationValidationCode(code)
        for code in find_stage2_response_quality_codes(result.flawed_ai_response)
    )

    if len(result.generated_errors) != expected_error_count:
        codes.append(Stage2GenerationValidationCode.ERROR_COUNT_MISMATCH)

    seen_error_sentences: set[str] = set()
    generated_types: set[str] = set()
    for error in result.generated_errors:
        generated_types.add(error.error_type)
        codes.extend(
            _validate_error_draft(
                error=error,
                allowed_types=allowed_types,
                document_text=document_text,
                normalized_document=normalized_document,
                normalized_flawed=normalized_flawed,
                flawed_ai_response=result.flawed_ai_response,
                seen_error_sentences=seen_error_sentences,
                evidence_match_threshold=threshold,
            )
        )

    if (
        allowed_types
        and expected_error_count >= len(allowed_types)
        and not allowed_types <= generated_types
    ):
        codes.append(Stage2GenerationValidationCode.ERROR_TYPE_COVERAGE_MISMATCH)

    deduped = tuple(dict.fromkeys(codes))
    return Stage2GenerationValidationResult(is_valid=not deduped, codes=deduped)


def _validate_error_draft(
    *,
    error: Stage2GeneratedErrorDraft,
    allowed_types: set[str],
    document_text: str,
    normalized_document: str,
    normalized_flawed: str,
    flawed_ai_response: str,
    seen_error_sentences: set[str],
    evidence_match_threshold: float,
) -> list[Stage2GenerationValidationCode]:
    codes: list[Stage2GenerationValidationCode] = []

    normalized_error_sentence = _normalize(error.error_sentence)
    if normalized_error_sentence in seen_error_sentences:
        codes.append(Stage2GenerationValidationCode.DUPLICATED_ERROR)
    else:
        seen_error_sentences.add(normalized_error_sentence)

    if error.error_type not in allowed_types:
        codes.append(Stage2GenerationValidationCode.INVALID_ERROR_TYPE)

    if not _text_exists_in_source(
        error.error_sentence,
        normalized_source=normalized_flawed,
        raw_source=flawed_ai_response,
        match_threshold=evidence_match_threshold,
    ):
        codes.append(Stage2GenerationValidationCode.ERROR_SENTENCE_NOT_FOUND)

    if has_similar_response_sentence(
        error.correct_sentence,
        flawed_ai_response=flawed_ai_response,
        match_threshold=evidence_match_threshold,
    ):
        codes.append(Stage2GenerationValidationCode.CORRECT_ANSWER_EXPOSED)

    if has_similar_response_sentence(
        error.error_sentence,
        flawed_ai_response=flawed_ai_response,
        match_threshold=evidence_match_threshold,
        exclude_exact=True,
    ):
        codes.append(Stage2GenerationValidationCode.UNLABELED_ERROR_DUPLICATE)

    if not _text_exists_in_source(
        error.evidence_sentence,
        normalized_source=normalized_document,
        raw_source=document_text,
        match_threshold=evidence_match_threshold,
    ):
        codes.append(Stage2GenerationValidationCode.EVIDENCE_NOT_FOUND)

    if error.error_type == "RETRIEVAL_ERROR" and not (error.retrieved_context or "").strip():
        codes.append(Stage2GenerationValidationCode.RETRIEVAL_CONTEXT_MISSING)

    return codes


def _text_exists_in_source(
    needle: str,
    *,
    normalized_source: str,
    raw_source: str,
    match_threshold: float,
) -> bool:
    normalized_needle = _normalize(needle)
    if not normalized_needle or not normalized_source:
        return False
    if normalized_needle in normalized_source:
        return True
    if needle.strip() and needle.strip() in raw_source:
        return True
    return _overlap_score(normalized_needle, normalized_source) >= match_threshold
