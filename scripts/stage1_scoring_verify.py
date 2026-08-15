"""Stage1 optimal 채점 검증 스크립트.

1) seed
2) 교사로 짧은 txt 과제 생성 (optimal 자동 탐색)
3) DB에서 optimal 확인
4) 학생으로 약함/optimal/max 파라미터 제출 → 점수 비교
5) docs/stage1-scoring-verify-result.html 생성
"""

from __future__ import annotations

import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx
from sqlalchemy import select, text

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from app.db.session import AsyncSessionLocal
from app.models.stage import Stage1AssignmentDetail

API = "http://localhost:8000/api/v1"
TEACHER = {"email": "e2e.teacher@example.com", "password": "Passw0rd!"}
STUDENT = {"email": "e2e.student@example.com", "password": "Passw0rd!"}
FIXED_Q = "오늘 학습 주제의 내용을 전체적으로 알려줘"

SAMPLE_DOC = """3·1 운동은 1919년 3월 1일 시작된 일제강점기 민족의 독립 운동입니다.
고종 황제 서거와 2·8 독립 선언을 계기로 전국에서 평화적 만세 시위가 확산되었습니다.
민족 대표의 독립 선언과 함께 학생·시민이 참여하였고, 이후 대한민국 임시 정부 수립으로 이어졌습니다.
문화 통치기로의 전환 이후에도 토지 조사와 회사령, 교육·언론 통제가 이어지며 억압이 누적되었습니다.
3·1 운동은 국내외 독립운동의 흐름과 국제 여론에 큰 영향을 주었습니다.
"""

# 자료에 맞춘 모범 답 (품질 점수용)
GOOD_ANSWER = (
    "1919년 3월 1일 시작된 3·1 운동은 일제강점기 민족의 독립 운동입니다. "
    "고종 황제 서거와 2·8 독립 선언을 계기로 평화적 만세 시위가 전국으로 확산되었고, "
    "대한민국 임시 정부 수립으로 이어졌습니다."
)


def login(client: httpx.Client, account: dict) -> str:
    r = client.post(f"{API}/auth/login", json=account, timeout=30)
    r.raise_for_status()
    return r.json()["access_token"]


async def read_optimal(assignment_id: int) -> dict | None:
    async with AsyncSessionLocal() as session:
        row = await session.scalar(
            select(Stage1AssignmentDetail).where(
                Stage1AssignmentDetail.assignment_id == assignment_id
            )
        )
        return dict(row.optimal_parameters) if row and row.optimal_parameters else None


async def main() -> None:
    # seed
    from scripts.seed_dev import seed

    await seed()

    results: dict = {"ok": False, "steps": []}

    with httpx.Client() as client:
        teacher_token = login(client, TEACHER)
        student_token = login(client, STUDENT)
        results["steps"].append("login ok")

        classes = client.get(
            f"{API}/teacher/classes",
            headers={"Authorization": f"Bearer {teacher_token}"},
            timeout=30,
        )
        if classes.status_code != 200:
            # fallback: query DB class for teacher
            async with AsyncSessionLocal() as session:
                class_id = await session.scalar(
                    text(
                        "SELECT class_id FROM classes WHERE teacher_id = "
                        "(SELECT user_id FROM users WHERE email = :email) "
                        "AND deleted_at IS NULL LIMIT 1"
                    ),
                    {"email": TEACHER["email"]},
                )
        else:
            data = classes.json()
            items = data.get("classes") or data
            if isinstance(items, list) and items:
                class_id = items[0].get("class_id") or items[0].get("id")
            else:
                class_id = None

        if not class_id:
            async with AsyncSessionLocal() as session:
                class_id = await session.scalar(
                    text(
                        "SELECT c.class_id FROM classes c "
                        "JOIN users u ON u.user_id = c.teacher_id "
                        "WHERE u.email = :email AND c.deleted_at IS NULL LIMIT 1"
                    ),
                    {"email": TEACHER["email"]},
                )
        results["class_id"] = class_id
        assert class_id, "class_id not found"

        due = (datetime.now(UTC) + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
        tmp = ROOT / "uploads" / "_verify_stage1.txt"
        tmp.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(SAMPLE_DOC, encoding="utf-8")

        print("creating assignment (preset embed + optimal search)...", flush=True)
        with tmp.open("rb") as f:
            create = client.post(
                f"{API}/teacher/assignments/step1",
                headers={"Authorization": f"Bearer {teacher_token}"},
                data={
                    "class_id": str(class_id),
                    "subject": "hist",
                    "due_at": due,
                    "default_chunk_size": "50",
                    "default_top_k": "2",
                    "default_temperature": "1.0",
                },
                files={"file": ("verify_31.txt", f, "text/plain")},
                timeout=300,
            )
        print("create status", create.status_code, create.text[:500], flush=True)
        create.raise_for_status()
        assignment_id = create.json()["assignment_id"]
        results["assignment_id"] = assignment_id
        results["steps"].append(f"create assignment_id={assignment_id}")

        optimal = await read_optimal(assignment_id)
        results["optimal_parameters"] = optimal
        print("optimal", optimal, flush=True)
        assert optimal, "optimal_parameters not saved"
        results["steps"].append(f"optimal={optimal}")

        # 동일 답으로 파라미터만 바꿔 3회 제출 (시도 한도 3)
        cases = [
            ("weak", {"chunk_size": 50, "top_k": 1, "temperature": 1.0}),
            (
                "optimal",
                {
                    "chunk_size": int(optimal["chunk_size"]),
                    "top_k": int(optimal["top_k"]),
                    "temperature": float(optimal["temperature"]),
                },
            ),
            ("max", {"chunk_size": 3000, "top_k": 10, "temperature": 0.0}),
        ]
        scores = []
        for name, params in cases:
            body = {
                "final_parameters": params,
                "selected_ai_response": GOOD_ANSWER,
                "student_prompt": FIXED_Q,
            }
            sub = client.post(
                f"{API}/student/assignments/{assignment_id}/step1/submit",
                headers={"Authorization": f"Bearer {student_token}"},
                json=body,
                timeout=120,
            )
            print(name, sub.status_code, sub.text[:400], flush=True)
            sub.raise_for_status()
            payload = sub.json()
            scores.append(
                {
                    "name": name,
                    "params": params,
                    "current_score": payload["current_score"],
                    "highest_score": payload["highest_score"],
                }
            )
            results["steps"].append(f"submit {name}={payload['current_score']}")

        results["scores"] = scores
        by_name = {s["name"]: s["current_score"] for s in scores}
        # optimal이 weak/max보다 높거나, 최소한 max가 optimal보다 크게 앞서지 않아야 함
        results["checks"] = {
            "optimal_ge_weak": by_name["optimal"] >= by_name["weak"],
            "optimal_ge_max_or_close": by_name["optimal"] + 5 >= by_name["max"],
            "optimal_saved": True,
        }
        results["ok"] = all(results["checks"].values())

    out = ROOT / "docs" / "stage1-scoring-verify-result.html"
    rows = "".join(
        f"<tr><td>{s['name']}</td><td><code>{json.dumps(s['params'])}</code></td>"
        f"<td class='score'>{s['current_score']}</td></tr>"
        for s in results.get("scores", [])
    )
    checks = "".join(
        f"<li>{k}: <strong>{'PASS' if v else 'FAIL'}</strong></li>"
        for k, v in results.get("checks", {}).items()
    )
    out.write_text(
        f"""<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8"/><title>Stage1 채점 검증 결과</title>
<style>
body{{font-family:Pretendard,-apple-system,sans-serif;margin:32px;color:#111}}
.ok{{color:#0a0}} .bad{{color:#c00}}
table{{border-collapse:collapse;width:100%;max-width:720px}}
td,th{{border:1px solid #ddd;padding:10px;text-align:left}}
code{{font-size:12px}} .score{{font-weight:700;font-size:18px}}
</style></head><body>
<h1>Stage1 채점 검증 결과</h1>
<p class="{'ok' if results['ok'] else 'bad'}">전체: {'PASS' if results['ok'] else 'FAIL'}</p>
<p>assignment_id: {results.get('assignment_id')}</p>
<p>optimal: <code>{json.dumps(results.get('optimal_parameters'), ensure_ascii=False)}</code></p>
<h2>제출 점수</h2>
<table><thead><tr><th>케이스</th><th>파라미터</th><th>점수</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>체크</h2><ul>{checks}</ul>
<p>공식: 최종 = 0.8×optimal근접 + 0.2×품질</p>
<p><a href="http://localhost:8000/docs" target="_blank">OpenAPI /docs</a></p>
</body></html>
""",
        encoding="utf-8",
    )
    print(json.dumps(results, ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0 if results["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()) or 0)
