"""Stage2 highlight submit smoke test."""

from __future__ import annotations

import json
import os
import sys
import uuid
from pathlib import Path

import httpx

BASE = "/api/v1"
ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "TEACHER_SECRET_CODE")
FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stage2_doc.txt"


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    api = f"{ROOT.rstrip('/')}{BASE}"

    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        fail(f"classes status={classes.status_code}")
    class_id = classes.json()["classes"][0]["class_id"]

    teacher_email = f"s2h-t-{suffix}@example.com"
    student_email = f"s2h-s-{suffix}@example.com"
    password_teacher = "S2Test123!"
    password_student = "S2Test456!"

    for email, name, role, extra in (
        (teacher_email, "S2HTeacher", "TEACHER", {"signup_code": TEACHER_CODE}),
        (student_email, "S2HStudent", "STUDENT", {}),
    ):
        signup = httpx.post(
            f"{api}/auth/signup",
            json={
                "email": email,
                "name": name,
                "phone": "010-5555-6666",
                "password": password_teacher if role == "TEACHER" else password_student,
                "role": role,
                "class_id": class_id,
                **extra,
            },
            timeout=30.0,
        )
        if signup.status_code != 201:
            fail(f"signup {role} status={signup.status_code} body={signup.text[:200]}")

    teacher_token = httpx.post(
        f"{api}/auth/login",
        json={"email": teacher_email, "password": password_teacher},
        timeout=30.0,
    ).json()["access_token"]

    with FIXTURE.open("rb") as doc:
        create = httpx.post(
            f"{api}/teacher/assignments/step2",
            headers={"Authorization": f"Bearer {teacher_token}"},
            data={
                "title": "2단계 하이라이트 테스트",
                "subject": "hist",
                "question": "장영실의 발명품에 대해 설명해줘.",
                "persona": "장영실이 연을 만들었다고 믿는 선생님",
                "hallucination_types": json.dumps(
                    ["PERSONA_BIAS", "RETRIEVAL_ERROR"], ensure_ascii=False
                ),
                "expected_error_count": "2",
            },
            files={"file": ("stage2_doc.txt", doc, "text/plain")},
            timeout=60.0,
        )
    if create.status_code != 201:
        fail(f"create status={create.status_code} body={create.text[:300]}")
    assignment_id = create.json()["assignment_id"]
    generated_errors = create.json()["generated_errors"]

    student_token = httpx.post(
        f"{api}/auth/login",
        json={"email": student_email, "password": password_student},
        timeout=30.0,
    ).json()["access_token"]

    target = next(
        (e for e in generated_errors if e["error_type"] == "RETRIEVAL_ERROR"),
        generated_errors[0],
    )
    payload = {
        "submissions": [
            {
                "highlighted_text": target["error_sentence"],
                "student_error_type": target["error_type"],
                "student_reason": (
                    "참고 문서에는 장영실이 세종 대에 자격루와 측우기를 발명한 "
                    "조선시대 과학자라고 나와 있습니다. "
                    "AI 답변의 서양 기술 도입 표현은 문서에 없는 내용이며 "
                    "잘못된 문서 검색으로 무관한 내용이 섞인 환각입니다."
                ),
            }
        ]
    }

    highlight = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step2/highlight",
        headers={"Authorization": f"Bearer {student_token}"},
        json=payload,
        timeout=60.0,
    )
    print(f"status={highlight.status_code}")
    if highlight.status_code != 200:
        fail(highlight.text[:500])

    body = highlight.json()
    required = [
        "is_all_correct",
        "highlight_phase_complete",
        "remaining_errors_to_find",
        "results",
        "attempts",
        "cleared_highlights",
    ]
    for key in required:
        if key not in body:
            fail(f"missing key: {key}")

    result = body["results"][0]
    report = result["evaluation_report"]
    for key in (
        "location_match_score",
        "error_type_match",
        "reasoning_score",
        "ai_feedback",
    ):
        if key not in report:
            fail(f"missing evaluation_report.{key}")

    if not result["is_correct"]:
        fail(
            f"expected is_correct=true got report={json.dumps(report, ensure_ascii=False)}"
        )
    if result["correct_answer"] is None:
        fail("correct_answer should be present when is_correct=true")
    if body["attempts"]["used_attempts"] != 1:
        fail("used_attempts should be 1")
    if body["attempts"]["remaining_attempts"] != 4:
        fail("remaining_attempts should be 4")
    if len(body["cleared_highlights"]) != 1:
        fail("cleared_highlights should have 1 item")
    if body["remaining_errors_to_find"] != 1:
        fail("remaining_errors_to_find should be 1 after first correct")

    print("OK stage2 highlight")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:1000])


if __name__ == "__main__":
    main()
