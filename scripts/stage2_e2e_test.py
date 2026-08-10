"""Stage 2 create→detail→highlight→correction E2E smoke test."""

from __future__ import annotations

import json
import mimetypes
import os
import sys
import uuid
from pathlib import Path

import httpx

BASE = "/api/v1"
ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "TEACHER_SECRET_CODE")
DEFAULT_FIXTURE = Path(__file__).resolve().parent / "fixtures" / "stage2_doc.txt"
BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.embedding_service import extract_text_from_upload  # noqa: E402
from app.services.stage2_document_context import (  # noqa: E402
    resolve_stage2_document_context,
)
from app.services.stage2_response_validation import (  # noqa: E402
    Stage2E2EValidationError,
    validate_stage2_create_response,
)


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def resolve_fixture_path() -> Path:
    env_path = os.getenv("STAGE2_TEST_FIXTURE", "").strip()
    if env_path:
        return Path(env_path)
    return DEFAULT_FIXTURE


def fixture_mime_type(fixture: Path) -> str:
    guessed, _ = mimetypes.guess_type(fixture.name)
    return guessed or "application/octet-stream"


def load_document_context(fixture: Path, question: str):
    content = fixture.read_bytes()
    source_text = extract_text_from_upload(fixture.name, content)
    return resolve_stage2_document_context(
        source_text=source_text,
        question=question,
    )


def build_student_reason(error: dict) -> str:
    evidence = error.get("evidence_sentence", "").strip()
    hallucination_reason = error.get("hallucination_reason", "").strip()
    return (
        f"참고 문서 근거 문장은 '{evidence}' 입니다. "
        f"AI 답변의 '{error['error_sentence']}' 구간은 {hallucination_reason} "
        f"따라서 {error['error_type']} 유형의 환각입니다."
    )


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
                "student_reason": build_student_reason(error),
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
        report = body["results"][0].get("evaluation_report", {})
        fail(
            "highlight not correct: "
            + json.dumps(
                {
                    "highlighted_text": body["results"][0].get("highlighted_text"),
                    "student_error_type": body["results"][0].get("student_error_type"),
                    "evaluation_report": report,
                    "evidence_sentence": error.get("evidence_sentence"),
                    "hallucination_reason": error.get("hallucination_reason"),
                },
                ensure_ascii=False,
            )[:1200]
        )
    return body


def main() -> None:
    suffix = uuid.uuid4().hex[:8]
    api = f"{ROOT.rstrip('/')}{BASE}"
    fixture = resolve_fixture_path()
    if not fixture.exists():
        fail(f"fixture missing: {fixture}")

    allowed_types = {
        value.strip().upper()
        for value in os.getenv(
            "STAGE2_TEST_HALLUCINATION_TYPES",
            "PERSONA_BIAS,RETRIEVAL_ERROR",
        ).split(",")
        if value.strip()
    }
    expected_error_count = int(
        os.getenv("STAGE2_TEST_EXPECTED_ERROR_COUNT", str(len(allowed_types)))
    )
    question = os.getenv(
        "STAGE2_TEST_QUESTION",
        "장영실의 발명품에 대해 설명해줘.",
    )
    persona = os.getenv(
        "STAGE2_TEST_PERSONA",
        "장영실이 연을 만들었다고 믿는 선생님",
    )
    document_context = load_document_context(fixture, question)
    document_text = document_context.generation_text

    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        fail(f"classes status={classes.status_code}")
    class_id = classes.json()["classes"][0]["class_id"]

    teacher_email = f"s2e-t-{suffix}@example.com"
    student_email = f"s2e-s-{suffix}@example.com"
    password_teacher = "S2Test123!"
    password_student = "S2Test456!"

    for email, name, role, extra in (
        (teacher_email, "S2ETeacher", "TEACHER", {"signup_code": TEACHER_CODE}),
        (student_email, "S2EStudent", "STUDENT", {}),
    ):
        signup = httpx.post(
            f"{api}/auth/signup",
            json={
                "email": email,
                "name": name,
                "phone": "010-9999-0000",
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

    with fixture.open("rb") as doc:
        create = httpx.post(
            f"{api}/teacher/assignments/step2",
            headers={"Authorization": f"Bearer {teacher_token}"},
            data={
                "title": os.getenv("STAGE2_TEST_TITLE", "2단계 E2E 테스트"),
                "subject": os.getenv("STAGE2_TEST_SUBJECT", "hist"),
                "question": question,
                "persona": persona,
                "hallucination_types": json.dumps(
                    sorted(allowed_types), ensure_ascii=False
                ),
                "expected_error_count": str(expected_error_count),
            },
            files={"file": (fixture.name, doc, fixture_mime_type(fixture))},
            timeout=180.0,
        )
    if create.status_code != 201:
        fail(f"create status={create.status_code} body={create.text[:400]}")

    create_body = create.json()
    try:
        validate_stage2_create_response(
            create_body,
            expected_error_count=expected_error_count,
            allowed_types=allowed_types,
            document_text=document_text,
        )
    except Stage2E2EValidationError as exc:
        fail(str(exc))

    assignment_id = create_body["assignment_id"]
    generated_errors = create_body["generated_errors"]
    print(
        json.dumps(
            {
                "stage": "create_ok",
                "assignment_id": assignment_id,
                "generated_error_types": [e["error_type"] for e in generated_errors],
                "evidence_sentences": [e.get("evidence_sentence", "")[:80] for e in generated_errors],
            },
            ensure_ascii=False,
        ),
        flush=True,
    )

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
    if detail.status_code != 200:
        fail(f"detail status={detail.status_code} body={detail.text[:400]}")
    detail_body = detail.json()
    if detail_body["flawed_ai_response"] != create_body["flawed_ai_response"]:
        fail("detail flawed_ai_response mismatch")
    if detail_body["expected_error_count"] != expected_error_count:
        fail("detail expected_error_count mismatch")

    last_highlight_body = None
    for error in generated_errors:
        last_highlight_body = submit_highlight(
            api, student_token, assignment_id, error
        )

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
    if correction.status_code != 200:
        fail(f"correction status={correction.status_code} body={correction.text[:400]}")

    correction_body = correction.json()
    if not correction_body.get("is_passed"):
        fail(f"correction not passed: {json.dumps(correction_body, ensure_ascii=False)[:500]}")
    if len(correction_body.get("feedback_details", [])) != expected_error_count:
        fail(f"feedback_details length should be {expected_error_count}")

    print("OK stage2 e2e")
    print(f"assignment_id={assignment_id}")
    print(f"fixture={fixture}")
    print(
        json.dumps(
            {
                "document_excerpt_applied": document_context.was_trimmed,
                "source_char_count": document_context.source_char_count,
                "generation_char_count": document_context.generation_char_count,
                "generated_error_types": [e["error_type"] for e in generated_errors],
                "score": correction_body.get("score"),
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
