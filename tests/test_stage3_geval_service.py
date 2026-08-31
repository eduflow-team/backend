from app.services.stage3_geval_service import _evaluate_correction_fallback, grade_stage3_corrections


def test_grade_stage3_corrections_empty_returns_full_reasoning_score() -> None:
    import asyncio

    report = asyncio.run(grade_stage3_corrections([], set(), []))
    assert report["reasoning_score"] == 100
    assert report["correction_rows"] == []


def test_fallback_correction_scores_reasonable() -> None:
    evaluation = _evaluate_correction_fallback(
        why_wrong="구체적인 연구 출처가 제시되지 않아 근거가 부족합니다.",
        correct_ground="교육부 발표 자료에 따르면 도입 사례가 제한적입니다.",
        fact_checker_why="구체적인 연구 출처가 제시되지 않았습니다.",
        reference_sources="- 교육부 AI 도입 현황 (연합뉴스)",
    )
    assert evaluation.why_rating >= 3
    assert evaluation.ground_rating >= 1
    assert evaluation.turn_score >= 20
