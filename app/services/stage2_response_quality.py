"""Stage 2 학생용 답변의 노출·슬롯 품질 검사."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

SLOT_MARKER_REMAINING = "SLOT_MARKER_REMAINING"
ANSWER_LEAKAGE_DETECTED = "ANSWER_LEAKAGE_DETECTED"

_SLOT_MARKER_PATTERN = re.compile(
    r"\[\[\s*ERROR_?\d+\s*\]\]",
    re.IGNORECASE,
)
_ANSWER_LEAKAGE_PATTERN = re.compile(
    "|".join(
        re.escape(phrase)
        for phrase in (
            "잘못 이해",
            "사실이 아니",
            "정확한 정보",
            "헷갈리",
            "혼동이 있",
            "알려져 있지만, 사실",
            "알려져 있지만 사실",
            "하지만 사실",
            "오해되는 경우",
            "잊지 말고",
            "기억해두",
            "기억하는 게 중요",
            "틀린 내용",
            "오류입니다",
            "오류예요",
        )
    ),
    re.IGNORECASE,
)


def find_stage2_response_quality_codes(flawed_ai_response: str) -> tuple[str, ...]:
    """학생용 답변에 생성 슬롯이나 정답 암시 표현이 남았는지 검사한다."""
    codes: list[str] = []
    if _SLOT_MARKER_PATTERN.search(flawed_ai_response):
        codes.append(SLOT_MARKER_REMAINING)
    if _ANSWER_LEAKAGE_PATTERN.search(flawed_ai_response):
        codes.append(ANSWER_LEAKAGE_DETECTED)
    return tuple(codes)


def has_similar_response_sentence(
    statement: str,
    *,
    flawed_ai_response: str,
    match_threshold: float,
    exclude_exact: bool = False,
) -> bool:
    """답변의 다른 문장에 정답 또는 유사 오류가 노출됐는지 검사한다."""
    normalized_statement = _normalize(statement)
    if not normalized_statement:
        return False

    response_sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+", flawed_ai_response)
        if sentence.strip()
    ]
    for sentence in response_sentences:
        normalized_sentence = _normalize(sentence)
        if not normalized_sentence:
            continue
        is_exact_location = (
            normalized_statement == normalized_sentence
            or normalized_statement in normalized_sentence
        )
        if exclude_exact and is_exact_location:
            continue
        if is_exact_location or (
            SequenceMatcher(
                None,
                normalized_statement,
                normalized_sentence,
            ).ratio()
            >= match_threshold
        ):
            return True
    return False


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())
