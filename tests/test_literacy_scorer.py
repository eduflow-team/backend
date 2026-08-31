"""literacy_scorer 단위 테스트."""

from app.services.grading.literacy_scorer import (
    StageAxisContribution,
    StageScoreInput,
    derive_literacy,
    derive_literacy_mixed,
    derive_literacy_phase1,
    derive_literacy_phase2,
)
from app.services.grading.stage4_grader import score_literacy_axes


def test_phase1_equal_copy_and_axis_average() -> None:
    axes = derive_literacy_phase1(
        [
            StageScoreInput(stage=1, score=80, status="COMPLETED"),
            StageScoreInput(stage=2, score=100, status="COMPLETED"),
            StageScoreInput(stage=4, score=60, status="COMPLETED"),
        ]
    )
    assert axes.ai_operation == 80
    assert axes.hallucination == 100
    assert axes.ethics == 60
    assert axes.ai_response == 90
    assert axes.critical == 80
    assert axes.collaboration == 70
    assert axes.total() == round((80 + 100 + 90 + 80 + 70 + 60) / 6)


def test_phase1_ignores_in_progress_and_keeps_best() -> None:
    axes = derive_literacy_phase1(
        [
            StageScoreInput(stage=1, score=50, status="IN_PROGRESS"),
            StageScoreInput(stage=1, score=70, status="COMPLETED"),
            StageScoreInput(stage=1, score=90, status="COMPLETED"),
        ]
    )
    assert axes.ai_operation == 90
    assert axes.ai_response == 90
    assert axes.collaboration == 90
    assert axes.hallucination is None


def test_phase2_averages_axis_contributions_from_stages() -> None:
    axes = derive_literacy_phase2(
        [
            StageAxisContribution(
                stage=1,
                ai_operation=80,
                ai_response=70,
                collaboration=90,
            ),
            StageAxisContribution(
                stage=2,
                hallucination=100,
                critical=80,
                ai_response=90,
            ),
            StageAxisContribution(
                stage=4,
                ethics=60,
                critical=40,
                collaboration=50,
            ),
        ]
    )
    assert axes.ai_operation == 80
    assert axes.hallucination == 100
    assert axes.ethics == 60
    assert axes.ai_response == 80
    assert axes.critical == 60
    assert axes.collaboration == 70


def test_mixed_copy_when_no_axes_axis_when_present() -> None:
    """1·2·3 점수만 → 복붙, Stage4 축값 → 축 투입."""
    axes = derive_literacy_mixed(
        [
            StageScoreInput(stage=1, score=80, status="COMPLETED"),
            StageScoreInput(stage=2, score=100, status="COMPLETED"),
            StageScoreInput(
                stage=4,
                score=70,
                status="COMPLETED",
                literacy_axes={
                    "ethics": 90,
                    "critical": 50,
                    "collaboration": 40,
                },
            ),
        ]
    )
    assert axes.ai_operation == 80  # stage1 copy
    assert axes.hallucination == 100  # stage2 copy
    assert axes.ethics == 90  # stage4 axis
    assert axes.critical == 75  # avg(100 stage2 copy, 50 stage4)
    assert axes.collaboration == 60  # avg(80 stage1, 40 stage4)
    assert axes.ai_response == 90  # avg(80, 100)


def test_mixed_stage123_can_also_send_axes() -> None:
    axes = derive_literacy_mixed(
        [
            StageScoreInput(
                stage=1,
                score=50,
                status="COMPLETED",
                literacy_axes={
                    "ai_operation": 70,
                    "ai_response": 60,
                    "collaboration": 80,
                },
            ),
        ]
    )
    assert axes.ai_operation == 70
    assert axes.ai_response == 60
    assert axes.collaboration == 80
    assert axes.ethics is None


def test_derive_literacy_default_is_mixed() -> None:
    axes = derive_literacy(
        stage_scores=[
            StageScoreInput(stage=4, score=60, status="COMPLETED"),
        ]
    )
    assert axes.ethics == 60  # copy path


def test_stage4_literacy_axes_formula() -> None:
    lit = score_literacy_axes(
        clear_score=40,
        efficiency_score=30,
        breakdown={
            "successful_attacks": 6,
            "failed_attacks": 6,
            "why_breached": 9,
            "defense_ideas": 9,
        },
        hard_clear_points=20,
    )
    assert lit.ethics == 100
    assert lit.critical == 100
    assert lit.collaboration == 100

    lit2 = score_literacy_axes(
        clear_score=20,
        efficiency_score=0,
        breakdown={
            "successful_attacks": 0,
            "failed_attacks": 0,
            "why_breached": 0,
            "defense_ideas": 0,
        },
        hard_clear_points=0,
    )
    assert lit2.ethics == 0
    assert lit2.critical == 0
    assert lit2.collaboration == 20  # 0.4 * (20/40) * 100
