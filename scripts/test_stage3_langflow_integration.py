"""Stage3LangflowClient + build_turns integration smoke test."""

from __future__ import annotations

import asyncio
import json
import os
import sys

# backend root on path
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "backend"))
sys.path.insert(0, ROOT)
os.environ.setdefault("LANGFLOW_URL", "http://localhost:7860")
os.environ.setdefault("LANGFLOW_STAGE3_V2_FLOW_ID", "34b4c97d-d994-4eff-9576-608153cb9e11")

from app.clients.stage3_langflow_client import Stage3LangflowClient
from app.services.stage3_debate import build_turns, grade_usage


TOPICS = [
    "학교에 AI 시험 감독 시스템을 도입해야 하는가?",
    "국가가 AI 생성 콘텐츠에 워터마크를 의무화해야 하는가?",
    "대학 입시에서 AI 면접을 도입해야 하는가?",
]


async def run_one(client: Stage3LangflowClient, topic: str) -> dict:
    result = await client.run_debate(
        topic=topic,
        pro_persona="효율성을 강조하는 교육 전문가",
        con_persona="개인정보 침해를 우려하는 인권 전문가",
        fact_persona="중립적인 과학 기자",
        mode="v2",
    )
    payload = build_turns(
        [
            {"role": "pro", "text": result.pro_argument},
            {"role": "con", "text": result.con_argument},
            {"role": "rebut", "text": result.rebuttal_argument},
        ],
        result.fact_check,
        topic=topic,
        pro_role="효율성을 강조하는 교육 전문가",
        con_role="개인정보 침해를 우려하는 인권 전문가",
        source=result.source,
        mode="v2",
    )
    turns = payload.get("turns") or []
    suspicious = [t for t in turns if t.get("verdict") in {"exaggerated", "unsupported", "false"}]
    report = grade_usage(turns, {str(suspicious[0]["id"])} if suspicious else set())
    return {
        "topic": topic,
        "source": result.source,
        "turn_count": len(turns),
        "turn_ids": [t.get("id") for t in turns],
        "suspicious_count": len(suspicious),
        "sample_verdicts": [
            {"id": t.get("id"), "verdict": t.get("verdict"), "claim": (t.get("claim") or "")[:60]}
            for t in turns
        ],
        "grade_if_first_suspicious_checked": report["score"] if suspicious else None,
    }


async def main() -> None:
    client = Stage3LangflowClient()
    results = []
    for topic in TOPICS:
        print(f"\n=== {topic} ===")
        row = await run_one(client, topic)
        results.append(row)
        print(json.dumps(row, ensure_ascii=False, indent=2))

    ok = all(r["source"] == "langflow" and r["turn_count"] >= 2 for r in results)
    print("\n" + "=" * 60)
    print(f"backend integration: {'OK' if ok else 'FAIL'} ({len(results)} topics)")
    if not ok:
        raise SystemExit(1)


if __name__ == "__main__":
    asyncio.run(main())
