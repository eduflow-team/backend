"""Stage2 하이라이트 Rule-based 채점 (위치·유형)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.core.config import settings
from app.models.stage import Stage2ErrorAnswer


@dataclass(frozen=True)
class HighlightLocationMatch:
    answer: Stage2ErrorAnswer
    overlap_score: float


class HighlightGrader:
    def match_location(
        self,
        highlighted_text: str,
        error_answers: list[Stage2ErrorAnswer],
    ) -> HighlightLocationMatch | None:
        """정답 오류 구간 중 overlap이 가장 높은 항목을 반환한다."""

        best: HighlightLocationMatch | None = None
        normalized_highlight = _normalize(highlighted_text)
        if not normalized_highlight:
            return None

        for answer in error_answers:
            error_sentence = answer.error_sentence or ""
            normalized_error = _normalize(error_sentence)
            if not normalized_error:
                continue

            score = _overlap_score(normalized_highlight, normalized_error)
            if best is None or score > best.overlap_score:
                best = HighlightLocationMatch(answer=answer, overlap_score=score)

        return best

    def is_location_match(self, overlap_score: float) -> bool:
        return overlap_score >= settings.STAGE2_LOCATION_THRESHOLD

    @staticmethod
    def is_type_match(student_error_type: str, matched_error_type: str | None) -> bool:
        if not matched_error_type:
            return False
        return student_error_type.strip().upper() == matched_error_type.strip().upper()

    def is_similar_text(self, left: str, right: str) -> bool:
        normalized_left = _normalize(left)
        normalized_right = _normalize(right)
        if not normalized_left or not normalized_right:
            return False
        if normalized_left == normalized_right:
            return True
        return _overlap_score(normalized_left, normalized_right) >= settings.STAGE2_LOCATION_THRESHOLD


def _normalize(text: str) -> str:
    cleaned = re.sub(r"\s+", " ", (text or "").strip().lower())
    return cleaned


def _overlap_score(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left in right or right in left:
        shorter = min(len(left), len(right))
        longer = max(len(left), len(right))
        return min(1.0, shorter / longer) if longer else 0.0
    return SequenceMatcher(None, left, right).ratio()
