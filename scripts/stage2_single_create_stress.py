"""단건 생성(POST /teacher/assignments/step2) 503 재현·회귀 확인 스크립트.

환각 유형 폴백이 동작하는지 보기 위해 동일 조건으로 N회 생성한다.
"""

from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path

import httpx

ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
API = f"{ROOT.rstrip('/')}/api/v1"
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "123456")
RUNS = int(os.getenv("STRESS_RUNS", "5"))
FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "2027 수능특강 동아시아사-excerpt.pdf"
)
QUESTION = os.getenv("STRESS_QUESTION", "명·청 교역과 관련된 내용을 설명해줘.")
PERSONA = os.getenv("STRESS_PERSONA", "청과의 교역을 과도하게 미화하는 역사 선생님")
# RETRIEVAL_ERROR를 첫 유형으로 두어 기존에 503이 잘 나던 조건을 재현한다
TYPES = os.getenv("STRESS_TYPES", "RETRIEVAL_ERROR,PERSONA_BIAS").split(",")


def teacher_token() -> str:
    suffix = uuid.uuid4().hex[:8]
    class_id = httpx.get(f"{API}/auth/classes", timeout=30.0).json()["classes"][0]["class_id"]
    email = f"stress-t-{suffix}@example.com"
    password = "Stress1!"
    res = httpx.post(
        f"{API}/auth/signup",
        json={
            "email": email,
            "name": "스트레스교사",
            "phone": "010-1111-0000",
            "password": password,
            "role": "TEACHER",
            "class_id": class_id,
            "signup_code": TEACHER_CODE,
        },
        timeout=30.0,
    )
    if res.status_code != 201:
        raise SystemExit(f"signup failed: {res.status_code} {res.text[:200]}")
    return httpx.post(
        f"{API}/auth/login",
        json={"email": email, "password": password},
        timeout=30.0,
    ).json()["access_token"]


def main() -> None:
    if not FIXTURE.exists():
        raise SystemExit(f"fixture missing: {FIXTURE}")

    token = teacher_token()
    results = []
    for run in range(1, RUNS + 1):
        started = time.perf_counter()
        with FIXTURE.open("rb") as doc:
            res = httpx.post(
                f"{API}/teacher/assignments/step2",
                headers={"Authorization": f"Bearer {token}"},
                data={
                    "title": f"단건 스트레스 {run}",
                    "subject": "hist",
                    "question": QUESTION,
                    "persona": PERSONA,
                    "hallucination_types": json.dumps(
                        [t.strip().upper() for t in TYPES if t.strip()],
                        ensure_ascii=False,
                    ),
                    "expected_error_count": "1",
                },
                files={"file": (FIXTURE.name, doc, "application/pdf")},
                timeout=600.0,
            )
        elapsed = round(time.perf_counter() - started, 1)
        body = res.json() if res.headers.get("content-type", "").startswith("application/json") else {}
        error_type = ""
        if res.status_code == 201:
            errors = body.get("generated_errors") or []
            error_type = errors[0].get("error_type", "") if errors else ""
        results.append(
            {
                "run": run,
                "status": res.status_code,
                "elapsed_sec": elapsed,
                "assignment_id": body.get("assignment_id"),
                "error_type": error_type,
                "detail": "" if res.status_code == 201 else str(body.get("detail", ""))[:80],
            }
        )
        print(json.dumps(results[-1], ensure_ascii=False), flush=True)

    ok = sum(1 for r in results if r["status"] == 201)
    print(f"\n== 단건 생성 {ok}/{RUNS} 성공 ==")
    types_used = [r["error_type"] for r in results if r["error_type"]]
    print(f"사용된 환각 유형: {types_used}")
    if ok < RUNS:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
