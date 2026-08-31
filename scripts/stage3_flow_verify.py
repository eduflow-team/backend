"""Stage 3 teacher preview + student sources E2E smoke test."""

from __future__ import annotations

import json
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

import httpx

BASE = "/api/v1"
ROOT = os.getenv("TEST_BASE_URL", "http://localhost:8000")
TEACHER_CODE = os.getenv("TEACHER_SIGNUP_CODE", "TEACHER_SECRET_CODE")
TOPIC = "생성형 AI를 교육 현장에 도입해야 하는가?"
NEEDS_CHECK = frozenset({"exaggerated", "unsupported", "false"})


def fail(msg: str) -> None:
    print(f"FAIL: {msg}")
    sys.exit(1)


def signup(api: str, email: str, name: str, role: str, password: str, class_id: int, **extra) -> None:
    payload = {
        "email": email,
        "name": name,
        "phone": "010-9999-0000",
        "password": password,
        "role": role,
        "class_id": class_id,
        **extra,
    }
    response = httpx.post(f"{api}/auth/signup", json=payload, timeout=60.0)
    if response.status_code != 201:
        fail(f"signup {role}: {response.status_code} {response.text[:400]}")


def login(api: str, email: str, password: str) -> str:
    response = httpx.post(
        f"{api}/auth/login",
        json={"email": email, "password": password},
        timeout=60.0,
    )
    if response.status_code != 200:
        fail(f"login: {response.status_code} {response.text[:400]}")
    return response.json()["access_token"]


def pick_class_id(api: str, teacher_token: str) -> int:
    response = httpx.get(
        f"{api}/teacher/classes",
        headers={"Authorization": f"Bearer {teacher_token}"},
        timeout=30.0,
    )
    if response.status_code == 200:
        classes = response.json().get("classes") or []
        if classes:
            return int(classes[0]["class_id"])
    response = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if response.status_code != 200:
        fail(f"classes: {response.status_code} {response.text[:300]}")
    classes = response.json().get("classes") or []
    if not classes:
        fail("no classes available")
    return int(classes[0]["class_id"])


def flawed_from_preview(debate: dict) -> list[dict]:
    rows: list[dict] = []
    for turn in debate.get("turns") or []:
        for claim in turn.get("claims") or []:
            verdict = str(claim.get("verdict") or "").lower()
            if verdict in NEEDS_CHECK:
                rows.append(
                    {
                        "turn_id": turn.get("id"),
                        "claim": str(claim.get("claim") or ""),
                        "verdict": verdict,
                        "reason": str(claim.get("reason") or ""),
                    }
                )
        turn_verdict = str(turn.get("verdict") or "").lower()
        if turn_verdict in NEEDS_CHECK:
            rows.append(
                {
                    "turn_id": turn.get("id"),
                    "claim": str(turn.get("claim") or turn.get("text") or "")[:120],
                    "verdict": turn_verdict,
                    "reason": str(turn.get("why") or ""),
                }
            )
    return rows


def main() -> None:
    api = f"{ROOT.rstrip('/')}{BASE}"
    suffix = uuid.uuid4().hex[:8]
    teacher_email = f"s3-t-{suffix}@example.com"
    student_email = f"s3-s-{suffix}@example.com"
    teacher_password = "PwTeacher123!"
    student_password = "PwStudent456!"

    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        fail(f"auth/classes: {classes.status_code}")
    class_id = int(classes.json()["classes"][0]["class_id"])

    signup(
        api,
        teacher_email,
        "S3Teacher",
        "TEACHER",
        teacher_password,
        class_id,
        signup_code=TEACHER_CODE,
    )
    signup(api, student_email, "S3Student", "STUDENT", student_password, class_id)

    teacher_token = login(api, teacher_email, teacher_password)
    student_token = login(api, student_email, student_password)
    class_id = pick_class_id(api, teacher_token)

    due_at = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    create = httpx.post(
        f"{api}/teacher/assignments/step3",
        headers={"Authorization": f"Bearer {teacher_token}"},
        json={
            "class_id": class_id,
            "topic": TOPIC,
            "title": f"[E2E] {TOPIC[:24]}",
            "subject": "AI·미디어 리터러시",
            "pro_persona": "교육 혁신을 강조하는 찬성 AI",
            "con_persona": "프라이버시와 편향을 우려하는 반대 AI",
            "fact_persona": "뉴스 근거를 중시하는 팩트체커",
            "debate_mode": "v2",
            "due_at": due_at,
        },
        timeout=60.0,
    )
    if create.status_code != 201:
        fail(f"create step3: {create.status_code} {create.text[:400]}")
    assignment_id = create.json()["assignment_id"]
    print(f"assignment_id={assignment_id}")

    preview = httpx.post(
        f"{api}/teacher/assignments/{assignment_id}/step3/preview-debate",
        headers={"Authorization": f"Bearer {teacher_token}"},
        timeout=600.0,
    )
    if preview.status_code != 200:
        fail(f"preview: {preview.status_code} {preview.text[:500]}")
    preview_body = preview.json()
    flawed = flawed_from_preview(preview_body.get("debate") or {})
    print(f"teacher preview: reused={preview_body.get('reused')} flawed={len(flawed)}")
    for i, row in enumerate(flawed[:5], start=1):
        print(f"  [{i}] {row['verdict']} | {row['claim'][:70]}")
        if row["reason"]:
            print(f"       why: {row['reason'][:90]}")

    debate = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step3/debate",
        headers={"Authorization": f"Bearer {student_token}"},
        json={},
        timeout=600.0,
    )
    if debate.status_code != 200:
        fail(f"debate: {debate.status_code} {debate.text[:500]}")
    turns = (debate.json().get("debate") or {}).get("turns") or []
    print(f"student debate: turns={len(turns)}")

    sample = flawed[:3]
    if not sample and turns:
        sample = [{"turn_id": turns[0]["id"], "claim": turns[0].get("claim") or ""}]

    ok_articles = 0
    for item in sample:
        sources = httpx.post(
            f"{api}/student/assignments/{assignment_id}/step3/sources",
            headers={"Authorization": f"Bearer {student_token}"},
            json={"turn_id": item["turn_id"], "claim": item["claim"]},
            timeout=60.0,
        )
        if sources.status_code != 200:
            fail(f"sources: {sources.status_code} {sources.text[:400]}")
        body = sources.json()
        articles = body.get("articles") or []
        searches = body.get("searches") or []
        print(
            f"\n  turn {item['turn_id']} articles={len(articles)} searches={len(searches)}"
        )
        print(f"  claim: {item['claim'][:80]}")
        for j, article in enumerate(articles[:2], start=1):
            print(f"    [{j}] {article.get('title', '')[:72]} ({article.get('source', '')})")
            print(f"        {article.get('url', '')[:90]}")
        if articles and not searches:
            ok_articles += 1

    passed = len(flawed) >= 2 and ok_articles >= min(2, len(sample)) and len(turns) >= 4
    result = {
        "pass": passed,
        "assignment_id": assignment_id,
        "teacher_email": teacher_email,
        "teacher_password": teacher_password,
        "student_email": student_email,
        "student_password": student_password,
        "flawed_count": len(flawed),
        "source_checks_ok": ok_articles,
    }
    print("\n=== RESULT ===")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if not passed:
        fail("stage3 flow checks did not pass")


if __name__ == "__main__":
    main()
