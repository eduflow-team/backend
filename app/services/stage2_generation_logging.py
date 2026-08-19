"""Stage 2 생성 파이프라인 관측 로그."""

from __future__ import annotations

import logging
from collections import Counter

from app.schemas.stage2_generation import Stage2GeneratedErrorDraft

logger = logging.getLogger(__name__)


def summarize_error_type_counts(
    errors: list[Stage2GeneratedErrorDraft],
) -> dict[str, int]:
    """오류 유형별 개수를 집계한다."""
    return dict(Counter(error.error_type for error in errors))


def log_stage2_generation_started(
    *,
    teacher_user_id: int,
    expected_error_count: int,
    hallucination_types: list[str],
    filename: str,
) -> None:
    logger.info(
        (
            "stage2 generation started "
            "teacher_user_id=%s expected_error_count=%s "
            "hallucination_types=%s filename=%s"
        ),
        teacher_user_id,
        expected_error_count,
        ",".join(hallucination_types),
        filename,
    )


def log_stage2_generation_attempt(
    *,
    teacher_user_id: int | None,
    attempt: int,
    max_attempts: int,
    duration_ms: float,
    failure_codes: tuple[str, ...],
    will_retry: bool,
) -> None:
    logger.info(
        (
            "stage2 generation attempt "
            "teacher_user_id=%s attempt=%s max_attempts=%s "
            "duration_ms=%.1f failure_codes=%s will_retry=%s"
        ),
        teacher_user_id,
        attempt,
        max_attempts,
        duration_ms,
        ",".join(failure_codes) if failure_codes else "-",
        will_retry,
    )


def log_stage2_generation_succeeded(
    *,
    teacher_user_id: int | None,
    assignment_id: int | None,
    generation_attempts: int,
    error_type_counts: dict[str, int],
) -> None:
    logger.info(
        (
            "stage2 generation succeeded "
            "teacher_user_id=%s assignment_id=%s generation_attempts=%s "
            "error_type_counts=%s"
        ),
        teacher_user_id,
        assignment_id,
        generation_attempts,
        error_type_counts,
    )


def log_stage2_generation_failed(
    *,
    teacher_user_id: int | None,
    generation_attempts: int,
    failure_codes: tuple[str, ...],
) -> None:
    logger.error(
        (
            "stage2 generation failed "
            "teacher_user_id=%s generation_attempts=%s failure_codes=%s"
        ),
        teacher_user_id,
        generation_attempts,
        ",".join(failure_codes) if failure_codes else "-",
    )
