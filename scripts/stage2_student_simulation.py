"""Stage2 student behavior simulation — wrong tries, recovery, correction variants."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import httpx

BASE = "/api/v1"
ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "TEACHER_SECRET_CODE")
DEFAULT_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "2027 수능특강 동아시아사-excerpt.pdf"
)


@dataclass
class Session:
    api: str
    teacher_token: str
    student_token: str
    fixture: Path


@dataclass
class ScenarioResult:
    name: str
    passed: bool
    detail: dict = field(default_factory=dict)


def log(msg: str) -> None:
    print(msg, flush=True)


def fixture_mime(fixture: Path) -> str:
    guessed, _ = mimetypes.guess_type(fixture.name)
    return guessed or "application/octet-stream"


def build_reason(error: dict, *, style: str = "good") -> str:
    evidence = error.get("evidence_sentence", "").strip()
    hallucination_reason = error.get("hallucination_reason", "").strip()
    if style == "weak":
        return "틀린 것 같아요. 문서랑 다른 내용인 것 같습니다."
    if style == "good":
        return (
            f"참고 문서 근거 문장은 '{evidence}' 입니다. "
            f"AI 답변의 '{error['error_sentence']}' 구간은 {hallucination_reason} "
            f"따라서 {error['error_type']} 유형의 환각입니다."
        )
    return hallucination_reason


def setup_session(fixture: Path) -> Session:
    suffix = uuid.uuid4().hex[:8]
    api = f"{ROOT.rstrip('/')}{BASE}"
    class_id = httpx.get(f"{api}/auth/classes", timeout=30.0).json()["classes"][0]["class_id"]

    teacher_email = f"sim-t-{suffix}@example.com"
    student_email = f"sim-s-{suffix}@example.com"
    teacher_password = "SimTest123!"
    student_password = "SimTest456!"

    for email, name, role, password, extra in (
        (teacher_email, "SimTeacher", "TEACHER", teacher_password, {"signup_code": TEACHER_CODE}),
        (student_email, "SimStudent", "STUDENT", student_password, {}),
    ):
        signup = httpx.post(
            f"{api}/auth/signup",
            json={
                "email": email,
                "name": name,
                "phone": "010-8888-0000",
                "password": password,
                "role": role,
                "class_id": class_id,
                **extra,
            },
            timeout=30.0,
        )
        if signup.status_code != 201:
            raise RuntimeError(f"signup failed: {signup.status_code} {signup.text[:200]}")

    teacher_token = httpx.post(
        f"{api}/auth/login",
        json={"email": teacher_email, "password": teacher_password},
        timeout=30.0,
    ).json()["access_token"]
    student_token = httpx.post(
        f"{api}/auth/login",
        json={"email": student_email, "password": student_password},
        timeout=30.0,
    ).json()["access_token"]
    return Session(api=api, teacher_token=teacher_token, student_token=student_token, fixture=fixture)


def create_assignment(session: Session, *, title: str) -> dict:
    types = os.getenv(
        "STAGE2_TEST_HALLUCINATION_TYPES",
        "PERSONA_BIAS,INFORMATION_FABRICATION",
    )
    max_tries = int(os.getenv("STAGE2_SIM_CREATE_RETRIES", "3"))
    last_error = ""
    for attempt in range(1, max_tries + 1):
        with session.fixture.open("rb") as doc:
            response = httpx.post(
                f"{session.api}/teacher/assignments/step2",
                headers={"Authorization": f"Bearer {session.teacher_token}"},
                data={
                    "title": title,
                    "subject": "hist",
                    "question": os.getenv(
                        "STAGE2_TEST_QUESTION",
                        "명·청 교역과 관련된 내용을 설명해줘.",
                    ),
                    "persona": os.getenv(
                        "STAGE2_TEST_PERSONA",
                        "청과의 교역을 과도하게 미화하는 역사 선생님",
                    ),
                    "hallucination_types": json.dumps(
                        [value.strip().upper() for value in types.split(",") if value.strip()],
                        ensure_ascii=False,
                    ),
                    "expected_error_count": os.getenv("STAGE2_TEST_EXPECTED_ERROR_COUNT", "2"),
                },
                files={"file": (session.fixture.name, doc, fixture_mime(session.fixture))},
                timeout=180.0,
            )
        if response.status_code == 201:
            return response.json()
        last_error = f"{response.status_code} {response.text[:200]}"
        if attempt < max_tries:
            time.sleep(2.0 * attempt)
    raise RuntimeError(f"create failed after {max_tries} tries: {last_error}")


def post_highlight(
    session: Session,
    assignment_id: int,
    *,
    highlighted_text: str,
    student_error_type: str,
    student_reason: str,
) -> dict:
    response = httpx.post(
        f"{session.api}/student/assignments/{assignment_id}/step2/highlight",
        headers={"Authorization": f"Bearer {session.student_token}"},
        json={
            "submissions": [
                {
                    "highlighted_text": highlighted_text,
                    "student_error_type": student_error_type,
                    "student_reason": student_reason,
                }
            ]
        },
        timeout=90.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"highlight http {response.status_code}: {response.text[:300]}")
    return response.json()


def post_correction(session: Session, assignment_id: int, corrections: list[dict]) -> dict:
    response = httpx.post(
        f"{session.api}/student/assignments/{assignment_id}/step2/correction",
        headers={"Authorization": f"Bearer {session.student_token}"},
        json={"corrections": corrections},
        timeout=90.0,
    )
    if response.status_code != 200:
        raise RuntimeError(f"correction http {response.status_code}: {response.text[:300]}")
    return response.json()


def pick_wrong_snippet(flawed: str, errors: list[dict]) -> str:
    error_sentences = {error["error_sentence"] for error in errors}
    for sentence in flawed.replace("\n", " ").split("."):
        chunk = sentence.strip()
        if len(chunk) < 12:
            continue
        if not any(error_sentence in chunk for error_sentence in error_sentences):
            return chunk + "."
    return flawed[:40]


def other_type(requested: str) -> str:
    options = ["PERSONA_BIAS", "INFORMATION_FABRICATION", "RETRIEVAL_ERROR"]
    for option in options:
        if option != requested:
            return option
    return "INFORMATION_FABRICATION"


def solve_highlight(
    session: Session,
    assignment_id: int,
    error: dict,
    *,
    prelude: list[dict] | None = None,
) -> dict:
    """Optional wrong attempts, then a good submission."""
    last_body: dict = {}
    for attempt in prelude or []:
        last_body = post_highlight(session, assignment_id, **attempt)
    last_body = post_highlight(
        session,
        assignment_id,
        highlighted_text=error["error_sentence"],
        student_error_type=error["error_type"],
        student_reason=build_reason(error, style="good"),
    )
    if not last_body["results"][0]["is_correct"]:
        report = last_body["results"][0]["evaluation_report"]
        raise RuntimeError(
            f"expected correct highlight: {json.dumps(report, ensure_ascii=False)}"
        )
    return last_body


def run_scenario_negative_highlights(session: Session) -> ScenarioResult:
    create = create_assignment(session, title="sim-negative-highlights")
    assignment_id = create["assignment_id"]
    errors = create["generated_errors"]
    flawed = create["flawed_ai_response"]
    error = errors[0]

    cases = [
        {
            "label": "wrong_location",
            "highlighted_text": pick_wrong_snippet(flawed, errors),
            "student_error_type": error["error_type"],
            "student_reason": build_reason(error, style="good"),
            "expect_correct": False,
        },
        {
            "label": "wrong_type",
            "highlighted_text": error["error_sentence"],
            "student_error_type": other_type(error["error_type"]),
            "student_reason": build_reason(error, style="good"),
            "expect_correct": False,
        },
        {
            "label": "weak_reason",
            "highlighted_text": error["error_sentence"],
            "student_error_type": error["error_type"],
            "student_reason": build_reason(error, style="weak"),
            "expect_correct": False,
        },
    ]

    outcomes: list[dict] = []
    for case in cases:
        body = post_highlight(
            session,
            assignment_id,
            highlighted_text=case["highlighted_text"],
            student_error_type=case["student_error_type"],
            student_reason=case["student_reason"],
        )
        item = body["results"][0]
        ok = item["is_correct"] == case["expect_correct"]
        outcomes.append(
            {
                "case": case["label"],
                "ok": ok,
                "is_correct": item["is_correct"],
                "report": item.get("evaluation_report", {}),
            }
        )

    passed = all(item["ok"] for item in outcomes)
    return ScenarioResult(
        name="negative_highlights",
        passed=passed,
        detail={"assignment_id": assignment_id, "outcomes": outcomes},
    )


def run_scenario_realistic_recovery(session: Session) -> ScenarioResult:
    create = create_assignment(session, title="sim-realistic-recovery")
    assignment_id = create["assignment_id"]
    errors = create["generated_errors"]
    attempts_log: list[dict] = []

    for index, error in enumerate(errors, start=1):
        wrong_body = post_highlight(
            session,
            assignment_id,
            highlighted_text=error["error_sentence"],
            student_error_type=other_type(error["error_type"]),
            student_reason=build_reason(error, style="weak"),
        )
        attempts_log.append(
            {
                "error_index": index,
                "attempt": "wrong_type_weak_reason",
                "is_correct": wrong_body["results"][0]["is_correct"],
            }
        )
        good_body = post_highlight(
            session,
            assignment_id,
            highlighted_text=error["error_sentence"],
            student_error_type=error["error_type"],
            student_reason=build_reason(error, style="good"),
        )
        attempts_log.append(
            {
                "error_index": index,
                "attempt": "correct",
                "is_correct": good_body["results"][0]["is_correct"],
                "highlight_phase_complete": good_body["highlight_phase_complete"],
            }
        )

    detail_resp = httpx.get(
        f"{session.api}/student/assignments/{assignment_id}/step2",
        headers={"Authorization": f"Bearer {session.student_token}"},
        timeout=30.0,
    ).json()
    passed = detail_resp.get("highlight_phase_complete") is True and all(
        entry.get("is_correct") is False
        for entry in attempts_log
        if entry["attempt"] == "wrong_type_weak_reason"
    ) and all(
        entry.get("is_correct") is True
        for entry in attempts_log
        if entry["attempt"] == "correct"
    )
    return ScenarioResult(
        name="realistic_recovery",
        passed=passed,
        detail={"assignment_id": assignment_id, "attempts": attempts_log},
    )


def run_scenario_perfect_to_pass(session: Session) -> ScenarioResult:
    create = create_assignment(session, title="sim-perfect-pass")
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
    return ScenarioResult(
        name="perfect_pass",
        passed=passed,
        detail={
            "assignment_id": assignment_id,
            "score": correction.get("score"),
            "is_passed": correction.get("is_passed"),
        },
    )


def run_scenario_weak_correction(session: Session) -> ScenarioResult:
    create = create_assignment(session, title="sim-weak-correction")
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
    passed = correction.get("is_passed") is False and correction.get("score", 100) < 100
    return ScenarioResult(
        name="weak_correction",
        passed=passed,
        detail={
            "assignment_id": assignment_id,
            "score": correction.get("score"),
            "is_passed": correction.get("is_passed"),
            "feedback_details": correction.get("feedback_details", []),
        },
    )


def main() -> int:
    fixture = Path(os.getenv("STAGE2_TEST_FIXTURE", str(DEFAULT_FIXTURE)))
    if not fixture.exists():
        log(f"FAIL: fixture missing: {fixture}")
        return 1

    session = setup_session(fixture)
    scenarios = [
        run_scenario_negative_highlights,
        run_scenario_realistic_recovery,
        run_scenario_perfect_to_pass,
        run_scenario_weak_correction,
    ]

    results: list[ScenarioResult] = []
    for runner in scenarios:
        log(f"\n=== {runner.__name__} ===")
        try:
            result = runner(session)
            results.append(result)
            log(json.dumps({"scenario": result.name, "passed": result.passed, **result.detail}, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            results.append(ScenarioResult(name=runner.__name__, passed=False, detail={"error": str(exc)}))
            log(f"ERROR {runner.__name__}: {exc}")

    summary = {
        "fixture": str(fixture),
        "total": len(results),
        "passed": sum(1 for item in results if item.passed),
        "failed": sum(1 for item in results if not item.passed),
        "scenarios": [{"name": item.name, "passed": item.passed, "detail": item.detail} for item in results],
    }
    out_path = Path(__file__).resolve().parent / "stage2_student_simulation_report.json"
    out_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    log("\n" + "=" * 60)
    log(f"SUMMARY passed={summary['passed']}/{summary['total']}")
    log(f"saved: {out_path}")
    return 0 if summary["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
