"""Stage1 퀴즈 채점 스모크 (정답 − 리소스 감점).

사용:
  docker exec -i eduflow_backend python scripts/stage1_scoring_verify.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.db.session import AsyncSessionLocal
from app.main import app

TEACHER = "e2e.teacher@example.com"
STUDENT = "e2e.student@example.com"
PASSWORD = "Passw0rd!"
OUT = Path("docs/stage1-scoring-verify-result.html")


async def login(client: AsyncClient, email: str) -> str:
    r = await client.post(
        "/api/v1/auth/login",
        json={"email": email, "password": PASSWORD},
    )
    r.raise_for_status()
    return r.json()["access_token"]


async def main() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        teacher_token = await login(client, TEACHER)
        student_token = await login(client, STUDENT)

        # class_id: 교사 소속 첫 학급
        async with AsyncSessionLocal() as s:
            row = (
                await s.execute(
                    text(
                        """
                        select c.class_id from classes c
                        join users u on u.user_id = c.teacher_id
                        where u.email = :email
                        limit 1
                        """
                    ),
                    {"email": TEACHER},
                )
            ).first()
        if not row:
            raise SystemExit("teacher class not found — seed 먼저 실행")
        class_id = int(row[0])

        due = (datetime.now(UTC) + timedelta(days=7)).isoformat()
        files = {
            "file": (
                "sample.txt",
                "3·1 운동 이후 대한민국 임시정부는 중국 상하이에 세워졌다.\n".encode(),
                "text/plain",
            )
        }
        data = {
            "class_id": str(class_id),
            "subject": "HISTORY",
            "question": "대한민국 임시정부는 어디에 세워졌나요?",
            "answer": "상하이",
            "due_at": due,
            "default_chunk_size": "50",
            "default_top_k": "2",
            "default_temperature": "1.0",
        }
        r = await client.post(
            "/api/v1/teacher/assignments/step1",
            headers={"Authorization": f"Bearer {teacher_token}"},
            data=data,
            files=files,
        )
        r.raise_for_status()
        assignment_id = r.json()["assignment_id"]
        print("created", assignment_id)

        cases = [
            ("correct_default", {"chunk_size": 50, "top_k": 2, "temperature": 1.0}, "상하이"),
            ("correct_high_k", {"chunk_size": 50, "top_k": 8, "temperature": 1.0}, "상하이"),
            ("wrong_default", {"chunk_size": 50, "top_k": 2, "temperature": 1.0}, "서울"),
        ]
        # 제출 2회 제한이므로 과제 3개 만들거나 첫 두 케이스만 — 여기선 케이스마다 새 과제 없이
        # 2회만 검증: correct_default vs correct_high_k
        results = []
        for name, params, answer in cases[:2]:
            sr = await client.post(
                f"/api/v1/student/assignments/{assignment_id}/step1/submit",
                headers={"Authorization": f"Bearer {student_token}"},
                json={"final_parameters": params, "student_answer": answer},
            )
            body = sr.json()
            print(name, sr.status_code, body)
            results.append({"name": name, "status": sr.status_code, "body": body})

        OUT.write_text(
            "<html><body><h1>stage1 scoring verify</h1><pre>"
            + json.dumps(results, ensure_ascii=False, indent=2)
            + "</pre></body></html>",
            encoding="utf-8",
        )
        print("wrote", OUT)


if __name__ == "__main__":
    asyncio.run(main())
