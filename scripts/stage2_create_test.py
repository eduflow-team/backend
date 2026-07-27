"""Stage2 teacher create smoke test."""

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

    teacher_email = f"s2-t-{suffix}@example.com"
    signup = httpx.post(
        f"{api}/auth/signup",
        json={
            "email": teacher_email,
            "name": "S2Teacher",
            "phone": "010-1111-2222",
            "password": "S2Test123!",
            "role": "TEACHER",
            "class_id": class_id,
            "signup_code": TEACHER_CODE,
        },
        timeout=30.0,
    )
    if signup.status_code != 201:
        fail(f"signup status={signup.status_code} body={signup.text[:300]}")

    login = httpx.post(
        f"{api}/auth/login",
        json={"email": teacher_email, "password": "S2Test123!"},
        timeout=30.0,
    )
    if login.status_code != 200:
        fail(f"login status={login.status_code}")
    token = login.json()["access_token"]

    if not FIXTURE.exists():
        fail(f"fixture missing: {FIXTURE}")

    with FIXTURE.open("rb") as doc:
        response = httpx.post(
            f"{api}/teacher/assignments/step2",
            headers={"Authorization": f"Bearer {token}"},
            data={
                "title": "2단계: 의도적 환각 비판적 검증 (테스트)",
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

    print(f"status={response.status_code}")
    print(response.text[:1200])
    if response.status_code != 201:
        fail("expected 201 Created")

    body = response.json()
    for key in (
        "assignment_id",
        "title",
        "question",
        "flawed_ai_response",
        "expected_error_count",
        "generated_errors",
    ):
        if key not in body:
            fail(f"missing response key: {key}")

    if body["expected_error_count"] != 2:
        fail("expected_error_count mismatch")
    if len(body["generated_errors"]) < 1:
        fail("generated_errors empty")

    print("OK stage2 create")
    print(f"assignment_id={body['assignment_id']}")


if __name__ == "__main__":
    main()
