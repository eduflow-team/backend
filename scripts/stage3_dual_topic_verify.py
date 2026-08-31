"""Stage3 news-first flow: 2 topics, teacher preview + student sources."""

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
PLACEHOLDER_MARKERS = ("(예시)", "news.google.com/search?")
TOPICS = [
    "생성형 AI를 교육 현장에 도입해야 하는가?",
    "학교 시험에 AI 부정행위 감독 시스템을 도입해야 하는가?",
]


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


def is_real_article(article: dict) -> bool:
    title = (article.get("title") or "").strip()
    url = (article.get("url") or "").strip()
    if len(title) < 4 or not url:
        return False
    blob = f"{title} {url}"
    return not any(marker in blob for marker in PLACEHOLDER_MARKERS)


def run_topic(
    api: str,
    *,
    teacher_token: str,
    student_token: str,
    class_id: int,
    topic: str,
    label: str,
) -> dict:
    due_at = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    create = httpx.post(
        f"{api}/teacher/assignments/step3",
        headers={"Authorization": f"Bearer {teacher_token}"},
        json={
            "class_id": class_id,
            "topic": topic,
            "title": f"[E2E] {topic[:20]}",
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
        fail(f"[{label}] create: {create.status_code} {create.text[:400]}")
    assignment_id = create.json()["assignment_id"]
    print(f"\n=== {label} ===")
    print(f"topic: {topic}")
    print(f"assignment_id={assignment_id}")

    preview = httpx.post(
        f"{api}/teacher/assignments/{assignment_id}/step3/preview-debate",
        headers={"Authorization": f"Bearer {teacher_token}"},
        timeout=600.0,
    )
    if preview.status_code != 200:
        fail(f"[{label}] preview: {preview.status_code} {preview.text[:500]}")
    turns = (preview.json().get("debate") or {}).get("turns") or []
    print(f"teacher preview turns={len(turns)} reused={preview.json().get('reused')}")

    debate = httpx.post(
        f"{api}/student/assignments/{assignment_id}/step3/debate",
        headers={"Authorization": f"Bearer {student_token}"},
        json={},
        timeout=600.0,
    )
    if debate.status_code != 200:
        fail(f"[{label}] student debate: {debate.status_code} {debate.text[:500]}")
    student_turns = (debate.json().get("debate") or {}).get("turns") or []
    print(f"student debate turns={len(student_turns)}")

    sample_turns = student_turns[:3]
    checks: list[dict] = []
    real_count = 0
    for turn in sample_turns:
        claim = turn.get("claim") or ""
        sources = httpx.post(
            f"{api}/student/assignments/{assignment_id}/step3/sources",
            headers={"Authorization": f"Bearer {student_token}"},
            json={"turn_id": turn.get("id"), "claim": claim},
            timeout=60.0,
        )
        if sources.status_code != 200:
            fail(f"[{label}] sources: {sources.status_code} {sources.text[:400]}")
        articles = sources.json().get("articles") or []
        real = [a for a in articles if is_real_article(a)]
        print(f"  turn {turn.get('id')}: articles={len(articles)} real={len(real)}")
        print(f"    claim: {(claim or turn.get('text') or '')[:80]}")
        for j, article in enumerate(real[:2], start=1):
            print(f"    [{j}] {article.get('title', '')[:72]} ({article.get('source', '')})")
        if real:
            real_count += 1
        checks.append(
            {
                "turn_id": turn.get("id"),
                "articles": len(articles),
                "real_articles": len(real),
                "titles": [a.get("title") for a in real[:2]],
            }
        )

    passed = len(student_turns) >= 4 and real_count >= min(2, len(sample_turns))
    return {
        "label": label,
        "topic": topic,
        "assignment_id": assignment_id,
        "turns": len(student_turns),
        "source_checks": checks,
        "real_source_turns": real_count,
        "pass": passed,
        "student_url": f"http://localhost:5173/student/stage/3?assignmentId={assignment_id}",
    }


def main() -> None:
    api = f"{ROOT.rstrip('/')}{BASE}"
    suffix = uuid.uuid4().hex[:8]
    teacher_email = f"s3-2t-{suffix}@example.com"
    student_email = f"s3-2s-{suffix}@example.com"
    teacher_password = "PwTeacher123!"
    student_password = "PwStudent456!"

    classes = httpx.get(f"{api}/auth/classes", timeout=30.0)
    if classes.status_code != 200:
        fail(f"auth/classes: {classes.status_code}")
    class_id = int(classes.json()["classes"][0]["class_id"])

    signup(
        api,
        teacher_email,
        "S3Teacher2",
        "TEACHER",
        teacher_password,
        class_id,
        signup_code=TEACHER_CODE,
    )
    signup(api, student_email, "S3Student2", "STUDENT", student_password, class_id)

    teacher_token = login(api, teacher_email, teacher_password)
    student_token = login(api, student_email, student_password)

    results = [
        run_topic(
            api,
            teacher_token=teacher_token,
            student_token=student_token,
            class_id=class_id,
            topic=topic,
            label=f"topic-{index + 1}",
        )
        for index, topic in enumerate(TOPICS)
    ]

    summary = {
        "teacher_email": teacher_email,
        "teacher_password": teacher_password,
        "student_email": student_email,
        "student_password": student_password,
        "results": results,
        "all_pass": all(item["pass"] for item in results),
    }
    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not summary["all_pass"]:
        fail("one or more topic checks failed")


if __name__ == "__main__":
    main()
