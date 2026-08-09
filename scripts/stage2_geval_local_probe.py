"""Probe G-Eval with a local OpenAI-compatible model (Ollama / vLLM)."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.services.grading.geval_service import GEvalService, resolve_geval_llm_config  # noqa: E402

_REFERENCE_DOCUMENT = (
    "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다. "
    "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, "
    "측우기는 비의 양을 재는 기구입니다."
)
_ERROR_SENTENCE = (
    "특히 자격루는 사실 서양에서 온 기계를 조선 시대에 맞게 발전시킨 것이라고 알려져 있어요."
)
_CORRECT_SENTENCE = "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다."
_HALLUCINATION_REASON = "문서에 서양 기술 전래에 대한 근거가 없습니다."
_STUDENT_REASON = (
    f"참고 문서에는 자격루가 물의 흐름을 이용한 물시계라고 나옵니다. "
    f"AI 답변의 '{_ERROR_SENTENCE}'는 {_HALLUCINATION_REASON} "
    "따라서 RETRIEVAL_ERROR 유형의 환각입니다."
)


async def main() -> int:
    config = resolve_geval_llm_config()
    if config is None:
        print(
            "G-Eval LLM not configured.\n"
            "Set GEVAL_LLM_BASE_URL + GEVAL_LLM_MODEL (Ollama) "
            "or OPENAI_API_KEY in .env",
            file=sys.stderr,
        )
        return 1

    print("G-Eval endpoint:", config.chat_completions_url)
    print("G-Eval model:", config.model)
    print("mode:", "local" if os.getenv("GEVAL_LLM_BASE_URL", "").strip() else "openai")
    print()

    service = GEvalService()

    print("[1/2] reasoning...")
    reasoning = await service.evaluate_reasoning(
        student_reason=_STUDENT_REASON,
        student_error_type="RETRIEVAL_ERROR",
        hallucination_reason=_HALLUCINATION_REASON,
        evidence_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
        reference_document=_REFERENCE_DOCUMENT,
        location_ok=True,
        type_ok=True,
    )
    print(" reasoning_score:", reasoning.reasoning_score)
    print(" feedback:", reasoning.ai_feedback)

    print("[2/2] correction...")
    correction = await service.evaluate_correction(
        student_answer=_CORRECT_SENTENCE,
        correct_sentence=_CORRECT_SENTENCE,
        original_highlight=_ERROR_SENTENCE,
        reference_document=_REFERENCE_DOCUMENT,
        hallucination_reason=_HALLUCINATION_REASON,
        evidence_sentence="자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다.",
    )
    print(" factual_accuracy:", correction.factual_accuracy)
    print(" completeness:", correction.completeness)
    print(" passed:", correction.is_item_passed)
    print(" feedback:", correction.ai_feedback)
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
