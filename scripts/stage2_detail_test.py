"""Stage2 student detail smoke test (requires existing stage2 assignment)."""

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

    teacher_email = f"s2d-t-{suffix}@example.com"
    student_email = f"s2d-s-{suffix}@example.com"
    password_teacher = "S2Test123!"
    password_student = "S2Test456!"

    for email, name, role, extra in (
        (teacher_email, "S2DTeacher", "TEACHER", {"signup_code": TEACHER_CODE}),
        (student_email, "S2DStudent", "STUDENT", {}),
    ):
        signup = httpx.post(
            f"{api}/auth/signup",
            json={
                "email": email,
                "name": name,
                "phone": "010-3333-4444",
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
                "title": "2단계 상세조회 테스트",
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

    student_token = httpx.post(
        f"{api}/auth/login",
        json={"email": student_email, "password": password_student},
        timeout=30.0,
    ).json()["access_token"]

    detail = httpx.get(
        f"{api}/student/assignments/{assignment_id}/step2",
        headers={"Authorization": f"Bearer {student_token}"},
        timeout=30.0,
    )
    print(f"status={detail.status_code}")
    if detail.status_code != 200:
        fail(detail.text[:500])

    body = detail.json()
    required = [
        "assignment_id",
        "title",
        "reference_document_text",
        "question",
        "flawed_ai_response",
        "expected_error_count",
        "hallucination_type_options",
        "hallucination_type_hints",
        "status",
        "highlight_phase_complete",
        "remaining_errors_to_find",
        "attempts",
        "cleared_highlights",
    ]
    for key in required:
        if key not in body:
            fail(f"missing key: {key}")

    if body["assignment_id"] != assignment_id:
        fail("assignment_id mismatch")
    if not body["reference_document_text"].strip():
        fail("reference_document_text empty")
    if not body["flawed_ai_response"].strip():
        fail("flawed_ai_response empty")
    if len(body["hallucination_type_options"]) != 3:
        fail("hallucination_type_options must be 3")
    if body["expected_error_count"] != 2:
        fail("expected_error_count mismatch")
    if body["highlight_phase_complete"] is not False:
        fail("highlight_phase_complete should be false initially")
    if body["remaining_errors_to_find"] != 2:
        fail("remaining_errors_to_find should be 2 initially")
    if body["attempts"]["max_attempts"] != 5:
        fail("max_attempts should be 5")

    print("OK stage2 detail")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:800])


if __name__ == "__main__":
    main()
