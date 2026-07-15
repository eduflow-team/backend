"""Stage2 correction submit smoke test (highlight 완료 후 1회 제출)."""

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


def submit_highlight(
    api: str,
    token: str,
    assignment_id: int,
    error: dict,
) -> dict:
    payload = {
        "submissions": [
            {
                "highlighted_text": error["error_sentence"],
                "student_error_type": error["error_type"],
                "student_reason": (
                    "참고 문서에는 장영실이 세종 대에 자격루와 측우기를 발명한 "
                    "조선시대 과학자라고 나와 있습니다. "
                    f"AI 답변의 '{error['error_sentence']}' 구간은 문서와 다른 환각이며 "
                    f"{error['error_type']} 유형에 해당합니다."
                ),
            }
        ]
    }
    response = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step2/highlight",
        headers={"Authorization": f"Bearer {token}"},
        json=payload,
        timeout=60.0,
    )
    if response.status_code != 200:
        fail(f"highlight status={response.status_code} body={response.text[:400]}")
    body = response.json()
    if not body["results"][0]["is_correct"]:
        fail(f"highlight not correct: {json.dumps(body, ensure_ascii=False)[:500]}")
    return body


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    api = f"{ROOT.rstrip('/')}{BASE}"

    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        fail(f"classes status={classes.status_code}")
    class_id = classes.json()["classes"][0]["class_id"]

    teacher_email = f"s2c-t-{suffix}@example.com"
    student_email = f"s2c-s-{suffix}@example.com"
    password_teacher = "S2Test123!"
    password_student = "S2Test456!"

    for email, name, role, extra in (
        (teacher_email, "S2CTeacher", "TEACHER", {"signup_code": TEACHER_CODE}),
        (student_email, "S2CStudent", "STUDENT", {}),
    ):
        signup = httpx.post(
            f"{api}/auth/signup",
            json={
                "email": email,
                "name": name,
                "phone": "010-7777-8888",
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
                "title": "2단계 correction 테스트",
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

    last_highlight_body = None
    for error in generated_errors:
        last_highlight_body = submit_highlight(api, student_token, assignment_id, error)

    if last_highlight_body is None or not last_highlight_body["highlight_phase_complete"]:
        fail("highlight_phase_complete should be true before correction")

    corrections_payload = {
        "corrections": [
            {
                "original_highlight": error["error_sentence"],
                "student_answer": error["correct_sentence"],
            }
            for error in generated_errors
        ]
    }

    correction = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step2/correction",
        headers={"Authorization": f"Bearer {student_token}"},
        json=corrections_payload,
        timeout=60.0,
    )
    print(f"status={correction.status_code}")
    if correction.status_code != 200:
        fail(correction.text[:500])

    body = correction.json()
    for key in ("is_passed", "score", "final_correct_sentence", "feedback_details"):
        if key not in body:
            fail(f"missing key: {key}")

    if len(body["feedback_details"]) != 2:
        fail("feedback_details length should be 2")
    if not body["is_passed"]:
        fail(f"expected is_passed=true body={json.dumps(body, ensure_ascii=False)[:600]}")
    if body["score"] != 100:
        fail(f"expected score=100 got {body['score']}")
    if not body["final_correct_sentence"].strip():
        fail("final_correct_sentence empty")

    retry = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step2/correction",
        headers={"Authorization": f"Bearer {student_token}"},
        json=corrections_payload,
        timeout=60.0,
    )
    if retry.status_code != 403:
        fail(f"re-submit should be 403 got {retry.status_code}")

    print("OK stage2 correction")
    print(json.dumps(body, ensure_ascii=False, indent=2)[:1200])


if __name__ == "__main__":
    main()
