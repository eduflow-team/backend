"""Run 10 Stage2 student answer variants and summarize results."""

from __future__ import annotations

import json
import os
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from scripts.stage2_student_simulation import (  # noqa: E402
    Session,
    build_reason,
    create_assignment,
    other_type,
    pick_wrong_snippet,
    post_correction,
    post_highlight,
    setup_session,
    solve_highlight,
)

RUN_COUNT = int(os.getenv("STAGE2_SIM_BATCH_RUNS", "10"))
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "2027 수능특강 동아시아사-excerpt.pdf"
)


@dataclass
class BatchRow:
    run: int
    case: str
    answer_type: str
    expected: str
    passed: bool
    assignment_id: int | None = None
    score: int | None = None
    reasoning_score: float | None = None
    location_score: float | None = None
    error: str = ""
    elapsed_sec: float = 0.0


def build_ambiguous_reason(error: dict) -> str:
    return (
        f"AI 답변의 '{error['error_sentence']}' 부분이 이상해 보입니다. "
        f"{error['error_type']} 유형일 수 있지만 근거는 잘 모르겠습니다."
    )


def build_partial_correction(error: dict) -> str:
    correct = error.get("correct_sentence", "").strip()
    if len(correct) > 20:
        return correct[:20] + "..."
    return "대충 고친 답변입니다."


def run_case(session: Session, run: int, case: str) -> BatchRow:
    started = time.perf_counter()
    try:
        if case == "wrong_location":
            create = create_assignment(session, title=f"batch-{run:02d}-wrong-location")
            errors = create["generated_errors"]
            body = post_highlight(
                session,
                create["assignment_id"],
                highlighted_text=pick_wrong_snippet(create["flawed_ai_response"], errors),
                student_error_type=errors[0]["error_type"],
                student_reason=build_reason(errors[0], style="good"),
            )
            item = body["results"][0]
            report = item["evaluation_report"]
            passed = item["is_correct"] is False
            return BatchRow(
                run=run,
                case=case,
                answer_type="오답(위치)",
                expected="highlight 실패",
                passed=passed,
                assignment_id=create["assignment_id"],
                reasoning_score=report.get("reasoning_score"),
                location_score=report.get("location_match_score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "wrong_type":
            create = create_assignment(session, title=f"batch-{run:02d}-wrong-type")
            error = create["generated_errors"][0]
            body = post_highlight(
                session,
                create["assignment_id"],
                highlighted_text=error["error_sentence"],
                student_error_type=other_type(error["error_type"]),
                student_reason=build_reason(error, style="good"),
            )
            item = body["results"][0]
            report = item["evaluation_report"]
            return BatchRow(
                run=run,
                case=case,
                answer_type="오답(유형)",
                expected="highlight 실패",
                passed=item["is_correct"] is False,
                assignment_id=create["assignment_id"],
                reasoning_score=report.get("reasoning_score"),
                location_score=report.get("location_match_score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "weak_reason":
            create = create_assignment(session, title=f"batch-{run:02d}-weak-reason")
            error = create["generated_errors"][0]
            body = post_highlight(
                session,
                create["assignment_id"],
                highlighted_text=error["error_sentence"],
                student_error_type=error["error_type"],
                student_reason=build_reason(error, style="weak"),
            )
            item = body["results"][0]
            report = item["evaluation_report"]
            return BatchRow(
                run=run,
                case=case,
                answer_type="애매(이유 짧음)",
                expected="highlight 실패",
                passed=item["is_correct"] is False,
                assignment_id=create["assignment_id"],
                reasoning_score=report.get("reasoning_score"),
                location_score=report.get("location_match_score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "ambiguous_reason":
            create = create_assignment(session, title=f"batch-{run:02d}-ambiguous")
            error = create["generated_errors"][0]
            body = post_highlight(
                session,
                create["assignment_id"],
                highlighted_text=error["error_sentence"],
                student_error_type=error["error_type"],
                student_reason=build_ambiguous_reason(error),
            )
            item = body["results"][0]
            report = item["evaluation_report"]
            return BatchRow(
                run=run,
                case=case,
                answer_type="애매(근거 없음)",
                expected="highlight 실패",
                passed=item["is_correct"] is False,
                assignment_id=create["assignment_id"],
                reasoning_score=report.get("reasoning_score"),
                location_score=report.get("location_match_score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "recovery":
            create = create_assignment(session, title=f"batch-{run:02d}-recovery")
            assignment_id = create["assignment_id"]
            error = create["generated_errors"][0]
            wrong = post_highlight(
                session,
                assignment_id,
                highlighted_text=error["error_sentence"],
                student_error_type=other_type(error["error_type"]),
                student_reason=build_reason(error, style="weak"),
            )
            right = post_highlight(
                session,
                assignment_id,
                highlighted_text=error["error_sentence"],
                student_error_type=error["error_type"],
                student_reason=build_reason(error, style="good"),
            )
            passed = (
                wrong["results"][0]["is_correct"] is False
                and right["results"][0]["is_correct"] is True
            )
            return BatchRow(
                run=run,
                case=case,
                answer_type="재시도(틀림→정답)",
                expected="1실패 후 통과",
                passed=passed,
                assignment_id=assignment_id,
                reasoning_score=right["results"][0]["evaluation_report"].get("reasoning_score"),
                location_score=right["results"][0]["evaluation_report"].get("location_match_score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "perfect_pass":
            create = create_assignment(session, title=f"batch-{run:02d}-perfect")
            assignment_id = create["assignment_id"]
            errors = create["generated_errors"]
            for error in errors:
                solve_highlight(session, assignment_id, error)
            correction = post_correction(
                session,
                assignment_id,
                [
                    {
                        "original_highlight": error["error_sentence"],
                        "student_answer": error["correct_sentence"],
                    }
                    for error in errors
                ],
            )
            passed = correction.get("is_passed") is True and correction.get("score") == 100
            return BatchRow(
                run=run,
                case=case,
                answer_type="정답(전체)",
                expected="score 100",
                passed=passed,
                assignment_id=assignment_id,
                score=correction.get("score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "weak_correction":
            create = create_assignment(session, title=f"batch-{run:02d}-weak-corr")
            assignment_id = create["assignment_id"]
            errors = create["generated_errors"]
            for error in errors:
                solve_highlight(session, assignment_id, error)
            correction = post_correction(
                session,
                assignment_id,
                [
                    {
                        "original_highlight": error["error_sentence"],
                        "student_answer": "잘 모르겠어요.",
                    }
                    for error in errors
                ],
            )
            passed = correction.get("is_passed") is False
            return BatchRow(
                run=run,
                case=case,
                answer_type="오답(수정문)",
                expected="correction 실패",
                passed=passed,
                assignment_id=assignment_id,
                score=correction.get("score"),
                elapsed_sec=time.perf_counter() - started,
            )

        if case == "partial_correction":
            create = create_assignment(session, title=f"batch-{run:02d}-partial-corr")
            assignment_id = create["assignment_id"]
            errors = create["generated_errors"]
            for error in errors:
                solve_highlight(session, assignment_id, error)
            correction = post_correction(
                session,
                assignment_id,
                [
                    {
                        "original_highlight": error["error_sentence"],
                        "student_answer": build_partial_correction(error),
                    }
                    for error in errors
                ],
            )
            passed = correction.get("is_passed") is False
            return BatchRow(
                run=run,
                case=case,
                answer_type="애매(부분 수정)",
                expected="correction 실패",
                passed=passed,
                assignment_id=assignment_id,
                score=correction.get("score"),
                elapsed_sec=time.perf_counter() - started,
            )

        raise ValueError(f"unknown case: {case}")
    except Exception as exc:  # noqa: BLE001
        return BatchRow(
            run=run,
            case=case,
            answer_type="error",
            expected="-",
            passed=False,
            error=str(exc)[:200],
            elapsed_sec=time.perf_counter() - started,
        )


CASE_ROTATION = [
    "wrong_location",
    "wrong_type",
    "weak_reason",
    "ambiguous_reason",
    "recovery",
    "perfect_pass",
    "weak_correction",
    "partial_correction",
    "perfect_pass",
    "recovery",
]


def main() -> int:
    fixture = Path(os.getenv("STAGE2_TEST_FIXTURE", str(DEFAULT_FIXTURE)))
    if not fixture.exists():
        print(f"FAIL: fixture missing: {fixture}")
        return 1

    session = setup_session(fixture)
    rows: list[BatchRow] = []
    for index in range(1, RUN_COUNT + 1):
        case = CASE_ROTATION[(index - 1) % len(CASE_ROTATION)]
        print(f"[{index}/{RUN_COUNT}] {case}...", flush=True)
        row = run_case(session, index, case)
        rows.append(row)
        print(
            json.dumps(
                {
                    "run": row.run,
                    "case": row.case,
                    "passed": row.passed,
                    "assignment_id": row.assignment_id,
                    "score": row.score,
                    "error": row.error,
                },
                ensure_ascii=False,
            ),
            flush=True,
        )

    passed_count = sum(1 for row in rows if row.passed)
    summary = {
        "fixture": str(fixture),
        "run_count": RUN_COUNT,
        "passed": passed_count,
        "failed": RUN_COUNT - passed_count,
        "rows": [row.__dict__ for row in rows],
    }
    out = Path(__file__).resolve().parent / "stage2_student_simulation_batch_report.json"
    out.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\nSUMMARY {passed_count}/{RUN_COUNT} saved={out}")
    return 0 if passed_count == RUN_COUNT else 1


if __name__ == "__main__":
    raise SystemExit(main())
