"""One-off Langflow raw output diagnostic."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx

from app.clients.langflow_client import build_stage2_langflow_tweaks
from app.core.config import settings
from app.services.embedding_service import extract_text_from_upload
from app.services.stage2_document_context import resolve_stage2_document_context
from app.services.stage2_retrieval_input import build_stage2_retrieval_input_from_candidates


async def main() -> None:
    fixture = Path("scripts/fixtures/2027 수능특강 동아시아사-excerpt.pdf")
    content = fixture.read_bytes()
    question = "명·청 교역과 관련된 내용을 설명해줘."
    raw = extract_text_from_upload(fixture.name, content)
    ctx = resolve_stage2_document_context(source_text=raw, question=question)
    retrieval = build_stage2_retrieval_input_from_candidates(ctx.chunk_candidates)
    tweaks = build_stage2_langflow_tweaks(
        gen_prompt_node_id=settings.LANGFLOW_STAGE2_GEN_PROMPT_NODE_ID,
        planner_prompt_node_id=settings.LANGFLOW_STAGE2_EXT_PROMPT_NODE_ID,
        document_text=ctx.generation_text,
        question=question,
        persona="청과의 교역을 과도하게 미화하는 역사 선생님",
        hallucination_types=["PERSONA_BIAS", "INFORMATION_FABRICATION"],
        expected_error_count=1,
        retrieval_input=retrieval,
    )
    url = f"{settings.LANGFLOW_URL.rstrip('/')}/api/v1/run/{settings.LANGFLOW_STAGE2_FLOW_ID}"
    headers = {"Content-Type": "application/json"}
    if settings.LANGFLOW_API_KEY:
        headers["x-api-key"] = settings.LANGFLOW_API_KEY

    async with httpx.AsyncClient(timeout=180.0) as client:
        response = await client.post(
            url,
            headers=headers,
            json={"input_value": "", "tweaks": tweaks},
        )
        print("status", response.status_code)
        data = response.json()

    texts: list[str] = []
    for run_output in data.get("outputs", []):
        for inner in run_output.get("outputs", []):
            results = inner.get("results", {})
            message = results.get("message") or results.get("text")
            if isinstance(message, dict) and message.get("text"):
                texts.append(message["text"])
            elif isinstance(message, str):
                texts.append(message)

    print("output_count", len(texts))
    for index, text in enumerate(texts):
        print(f"--- output {index} len={len(text)}")
        print(text[:2000])


if __name__ == "__main__":
    asyncio.run(main())
