"""Stage 2 create/E2E 응답 검증 헬퍼."""

from __future__ import annotations

from app.schemas.stage2 import ALLOWED_HALLUCINATION_TYPES


class Stage2E2EValidationError(ValueError):
    """Stage 2 smoke/E2E 검증 실패."""


def validate_generated_error_item(
    error: dict,
    *,
    flawed_ai_response: str,
    allowed_types: set[str] | frozenset[str],
    document_text: str | None = None,
) -> None:
    """단일 generated_error 항목 품질을 검증한다."""
    required_keys = {
        "answer_id",
        "error_sentence",
        "error_type",
        "start_index",
        "end_index",
        "correct_sentence",
        "hallucination_reason",
        "evidence_sentence",
    }
    missing = required_keys - set(error.keys())
    if missing:
        raise Stage2E2EValidationError(f"generated_errors missing keys: {sorted(missing)}")

    error_sentence = (error.get("error_sentence") or "").strip()
    error_type = (error.get("error_type") or "").strip().upper()
    evidence_sentence = (error.get("evidence_sentence") or "").strip()
    correct_sentence = (error.get("correct_sentence") or "").strip()
    hallucination_reason = (error.get("hallucination_reason") or "").strip()

    if not error_sentence:
        raise Stage2E2EValidationError("error_sentence is empty")
    if error_type not in ALLOWED_HALLUCINATION_TYPES:
        raise Stage2E2EValidationError(f"invalid error_type: {error_type}")
    if allowed_types and error_type not in allowed_types:
        raise Stage2E2EValidationError(
            f"error_type not in teacher selection: {error_type}"
        )
    if error_sentence not in flawed_ai_response:
        raise Stage2E2EValidationError("error_sentence not found in flawed_ai_response")
    if not evidence_sentence or not correct_sentence or not hallucination_reason:
        raise Stage2E2EValidationError("evidence/correct/reason must not be empty")

    start_index = error.get("start_index")
    end_index = error.get("end_index")
    if not isinstance(start_index, int) or not isinstance(end_index, int):
        raise Stage2E2EValidationError("start_index/end_index must be integers")
    if start_index < 0 or end_index <= start_index:
        raise Stage2E2EValidationError("invalid index span")
    if flawed_ai_response[start_index:end_index] != error_sentence:
        raise Stage2E2EValidationError("index span does not match error_sentence")

    if document_text and evidence_sentence not in document_text:
        raise Stage2E2EValidationError("evidence_sentence not found in document_text")


def validate_stage2_create_response(
    body: dict,
    *,
    expected_error_count: int,
    allowed_types: set[str] | frozenset[str],
    document_text: str | None = None,
) -> None:
    """create API 응답의 generated_errors 품질을 검증한다."""
    required_keys = {
        "assignment_id",
        "title",
        "question",
        "flawed_ai_response",
        "expected_error_count",
        "generated_errors",
    }
    missing = required_keys - set(body.keys())
    if missing:
        raise Stage2E2EValidationError(f"create response missing keys: {sorted(missing)}")

    if body["expected_error_count"] != expected_error_count:
        raise Stage2E2EValidationError("expected_error_count mismatch")

    flawed_ai_response = (body.get("flawed_ai_response") or "").strip()
    if not flawed_ai_response:
        raise Stage2E2EValidationError("flawed_ai_response is empty")

    generated_errors = body.get("generated_errors")
    if not isinstance(generated_errors, list):
        raise Stage2E2EValidationError("generated_errors must be a list")
    if len(generated_errors) != expected_error_count:
        raise Stage2E2EValidationError(
            f"generated_errors count mismatch: expected {expected_error_count}, "
            f"got {len(generated_errors)}"
        )

    seen_types: set[str] = set()
    for error in generated_errors:
        validate_generated_error_item(
            error,
            flawed_ai_response=flawed_ai_response,
            allowed_types=allowed_types,
            document_text=document_text,
        )
        seen_types.add(str(error["error_type"]).upper())

    if allowed_types and not seen_types <= set(allowed_types):
        raise Stage2E2EValidationError("generated error types exceed teacher selection")
