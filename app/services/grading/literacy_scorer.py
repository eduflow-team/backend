"""울산형 AI 리터러시 6축 환산.

혼합(현재):
- 단계가 축별 점수(literacy_axes)를 주면 → 해당 축에만 투입
- 100점 하나만 주면 → 단계 매핑 3축에 복붙
- 축별로 모인 값의 평균이 육각형 점수

1·2·3도 나중에 축별 점수를 저장하면 같은 경로로 들어간다.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

LiteracyAxisKey = Literal[
    "ai_operation",
    "hallucination",
    "ai_response",
    "critical",
    "collaboration",
    "ethics",
]

LITERACY_AXIS_KEYS: tuple[LiteracyAxisKey, ...] = (
    "ai_operation",
    "hallucination",
    "ai_response",
    "critical",
    "collaboration",
    "ethics",
)

# 단계 → 주요 리터러시 역량 (17차 회의)
STAGE_LITERACY_MAP: dict[int, tuple[LiteracyAxisKey, ...]] = {
    1: ("ai_operation", "ai_response", "collaboration"),
    2: ("hallucination", "critical", "ai_response"),
    3: ("collaboration", "critical", "ai_response"),
    4: ("ethics", "critical", "collaboration"),
}

# 2 = 혼합(축 있으면 축, 없으면 복붙)
LITERACY_SCORE_PHASE = 2


def clamp_score(score: float | int) -> int:
    return max(0, min(100, int(round(float(score)))))


def parse_literacy_axes_payload(raw: Any) -> dict[LiteracyAxisKey, int] | None:
    """final_parameters['literacy_axes'] 등에서 축 점수 dict 추출."""
    if not isinstance(raw, dict):
        return None
    out: dict[LiteracyAxisKey, int] = {}
    for key in LITERACY_AXIS_KEYS:
        if key not in raw or raw[key] is None:
            continue
        try:
            out[key] = clamp_score(raw[key])
        except (TypeError, ValueError):
            continue
    return out or None


@dataclass(frozen=True)
class StageScoreInput:
    """단계 기여분. literacy_axes가 있으면 축 투입, 없으면 score 복붙."""

    stage: int
    score: int
    status: str | None = None
    literacy_axes: dict[LiteracyAxisKey, int] | None = None


@dataclass(frozen=True)
class LiteracyAxes:
    ai_operation: int | None = None
    hallucination: int | None = None
    ai_response: int | None = None
    critical: int | None = None
    collaboration: int | None = None
    ethics: int | None = None

    def as_dict(self) -> dict[str, int | None]:
        return {
            "ai_operation": self.ai_operation,
            "hallucination": self.hallucination,
            "ai_response": self.ai_response,
            "critical": self.critical,
            "collaboration": self.collaboration,
            "ethics": self.ethics,
        }

    def total(self) -> int:
        """이수 축만 평균. 없으면 0."""
        vals = [v for v in self.as_dict().values() if v is not None]
        if not vals:
            return 0
        return int(round(sum(vals) / len(vals)))


def _is_completed(status: str | None) -> bool:
    if status is None or status == "":
        return True
    return str(status).upper() == "COMPLETED"


def collapse_stage_scores(stages: list[StageScoreInput]) -> list[StageScoreInput]:
    """COMPLETED + 점수 있는 단계만, 단계당 최고점. 동점이면 축값 있는 쪽 우선."""
    best: dict[int, StageScoreInput] = {}
    for item in stages:
        if item.score is None:
            continue
        if not _is_completed(item.status):
            continue
        if item.stage not in STAGE_LITERACY_MAP:
            continue
        score = clamp_score(item.score)
        normalized = StageScoreInput(
            stage=item.stage,
            score=score,
            status="COMPLETED",
            literacy_axes=item.literacy_axes,
        )
        prev = best.get(item.stage)
        if prev is None or normalized.score > prev.score:
            best[item.stage] = normalized
        elif (
            normalized.score == prev.score
            and normalized.literacy_axes
            and not prev.literacy_axes
        ):
            best[item.stage] = normalized
    return [best[stage] for stage in sorted(best.keys())]


def allocate_stage_score_equal(stage: int, score: int) -> dict[LiteracyAxisKey, int]:
    """점수만 있을 때: 단계 점수를 매핑 축에 동일 복사."""
    keys = STAGE_LITERACY_MAP.get(stage, ())
    clamped = clamp_score(score)
    return {key: clamped for key in keys}


def derive_literacy_phase1(stages: list[StageScoreInput]) -> LiteracyAxes:
    """1차 환산: 단계 점수 → 6축 (항상 복붙)."""
    buckets: dict[LiteracyAxisKey, list[int]] = {k: [] for k in LITERACY_AXIS_KEYS}
    for item in collapse_stage_scores(stages):
        for key, value in allocate_stage_score_equal(item.stage, item.score).items():
            buckets[key].append(value)
    return _average_buckets(buckets)


def derive_literacy_mixed(stages: list[StageScoreInput]) -> LiteracyAxes:
    """혼합: 축값 있으면 축 투입, 없으면 매핑 3축 복붙 → 축별 평균."""
    buckets: dict[LiteracyAxisKey, list[int]] = {k: [] for k in LITERACY_AXIS_KEYS}
    for item in collapse_stage_scores(stages):
        if item.literacy_axes:
            for key, value in item.literacy_axes.items():
                if key in LITERACY_AXIS_KEYS:
                    buckets[key].append(clamp_score(value))
        else:
            for key, value in allocate_stage_score_equal(item.stage, item.score).items():
                buckets[key].append(value)
    return _average_buckets(buckets)


# ---------------------------------------------------------------------------
# 명시 기여분 리스트 (테스트·직접 호출용)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageAxisContribution:
    """한 단계가 보낸 축별 점수. 모르는 축은 None/생략."""

    stage: int | None = None
    ai_operation: int | None = None
    hallucination: int | None = None
    ai_response: int | None = None
    critical: int | None = None
    collaboration: int | None = None
    ethics: int | None = None

    def axis_values(self) -> dict[LiteracyAxisKey, int]:
        raw = {
            "ai_operation": self.ai_operation,
            "hallucination": self.hallucination,
            "ai_response": self.ai_response,
            "critical": self.critical,
            "collaboration": self.collaboration,
            "ethics": self.ethics,
        }
        out: dict[LiteracyAxisKey, int] = {}
        for key, value in raw.items():
            if value is not None:
                out[key] = clamp_score(value)  # type: ignore[index]
        return out


def derive_literacy_phase2(
    contributions: list[StageAxisContribution],
) -> LiteracyAxes:
    """축 기여분만 모아 평균."""
    buckets: dict[LiteracyAxisKey, list[int]] = {k: [] for k in LITERACY_AXIS_KEYS}
    for contrib in contributions:
        for key, value in contrib.axis_values().items():
            buckets[key].append(value)
    return _average_buckets(buckets)


def derive_literacy(
    *,
    stage_scores: list[StageScoreInput] | None = None,
    axis_contributions: list[StageAxisContribution] | None = None,
    phase: int = LITERACY_SCORE_PHASE,
) -> LiteracyAxes:
    """진입점. phase>=2: 혼합(stage_scores 우선) 또는 명시 contributions."""
    if phase >= 2:
        if stage_scores:
            return derive_literacy_mixed(stage_scores)
        return derive_literacy_phase2(axis_contributions or [])
    return derive_literacy_phase1(stage_scores or [])


def _average_buckets(buckets: dict[LiteracyAxisKey, list[int]]) -> LiteracyAxes:
    averaged: dict[str, int | None] = {}
    for key in LITERACY_AXIS_KEYS:
        vals = buckets[key]
        averaged[key] = int(round(sum(vals) / len(vals))) if vals else None
    return LiteracyAxes(**averaged)
