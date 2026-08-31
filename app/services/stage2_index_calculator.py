"""Stage 2 오류 문장 위치 인덱스 서버 계산."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)


class Stage2IndexCalculationCode(StrEnum):
    ERROR_SENTENCE_NOT_FOUND = "ERROR_SENTENCE_NOT_FOUND"
    ERROR_SENTENCE_AMBIGUOUS = "ERROR_SENTENCE_AMBIGUOUS"


@dataclass(frozen=True)
class Stage2ErrorIndexSpan:
    start_index: int
    end_index: int


@dataclass(frozen=True)
class Stage2ErrorIndexResult:
    span: Stage2ErrorIndexSpan | None
    codes: tuple[Stage2IndexCalculationCode, ...]

    @property
    def is_success(self) -> bool:
        return self.span is not None and not self.codes


@dataclass(frozen=True)
class Stage2IndexApplicationResult:
    result: Stage2LangflowGenerationResult
    codes: tuple[Stage2IndexCalculationCode, ...]
    applied: bool


def calculate_error_index_span(
    *,
    error_sentence: str,
    flawed_ai_response: str,
) -> Stage2ErrorIndexResult:
    """`flawed_ai_response`에서 `error_sentence`의 start/end 인덱스를 계산한다."""
    needle = error_sentence.strip()
    if not needle:
        return Stage2ErrorIndexResult(
            span=None,
            codes=(Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND,),
        )

    positions = _find_substring_positions(flawed_ai_response, needle)
    if not positions:
        return Stage2ErrorIndexResult(
            span=None,
            codes=(Stage2IndexCalculationCode.ERROR_SENTENCE_NOT_FOUND,),
        )
    if len(positions) > 1:
        return Stage2ErrorIndexResult(
            span=None,
            codes=(Stage2IndexCalculationCode.ERROR_SENTENCE_AMBIGUOUS,),
        )

    start_index = positions[0]
    end_index = start_index + len(needle)
    return Stage2ErrorIndexResult(
        span=Stage2ErrorIndexSpan(start_index=start_index, end_index=end_index),
        codes=(),
    )


def apply_server_error_indices(
    result: Stage2LangflowGenerationResult,
) -> Stage2IndexApplicationResult:
    """LLM 인덱스를 무시하고 모든 오류 draft에 서버 계산 인덱스를 적용한다."""
    codes: list[Stage2IndexCalculationCode] = []
    spans: list[Stage2ErrorIndexSpan | None] = []

    for error in result.generated_errors:
        index_result = calculate_error_index_span(
            error_sentence=error.error_sentence,
            flawed_ai_response=result.flawed_ai_response,
        )
        codes.extend(index_result.codes)
        spans.append(index_result.span)

    deduped_codes = tuple(dict.fromkeys(codes))
    if deduped_codes:
        return Stage2IndexApplicationResult(
            result=result,
            codes=deduped_codes,
            applied=False,
        )

    updated_errors = [
        error.model_copy(
            update={
                "start_index": span.start_index,
                "end_index": span.end_index,
            }
        )
        for error, span in zip(result.generated_errors, spans)
        if span is not None
    ]
    return Stage2IndexApplicationResult(
        result=result.model_copy(update={"generated_errors": updated_errors}),
        codes=(),
        applied=True,
    )


def _find_substring_positions(text: str, needle: str) -> list[int]:
    positions: list[int] = []
    start = 0
    while start <= len(text):
        index = text.find(needle, start)
        if index == -1:
            break
        positions.append(index)
        start = index + len(needle)
    return positions
