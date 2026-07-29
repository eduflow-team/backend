"""Stage 2 PDF 본문에서 Langflow·학생 참고문서용 생성 컨텍스트를 구성한다."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.stage2_chunk_candidates import (
    Stage2ChunkCandidate,
    build_stage2_chunk_candidates,
    build_stage2_reference_excerpt,
)


@dataclass(frozen=True)
class Stage2DocumentContext:
    """업로드 원문과 생성 파이프라인에 사용할 excerpt."""

    source_text: str
    generation_text: str
    was_trimmed: bool
    source_char_count: int
    generation_char_count: int
    chunk_candidates: list[Stage2ChunkCandidate]


def resolve_stage2_document_context(
    *,
    source_text: str,
    question: str,
    max_generation_chars: int | None = None,
) -> Stage2DocumentContext:
    """질문 관련 excerpt를 생성 컨텍스트로 사용한다.

    짧은 문서는 그대로 전달하고, 긴 문서는 relevance 기준 발췌문을 만든다.
    Langflow, validator, 학생 reference_document_text는 generation_text를 사용한다.
    """
    normalized_source = source_text.strip()
    resolved_max_chars = (
        settings.STAGE2_GENERATION_DOCUMENT_MAX_CHARS
        if max_generation_chars is None
        else max_generation_chars
    )
    candidates = build_stage2_chunk_candidates(
        document_text=normalized_source,
        question=question,
    )

    if not normalized_source:
        return Stage2DocumentContext(
            source_text="",
            generation_text="",
            was_trimmed=False,
            source_char_count=0,
            generation_char_count=0,
            chunk_candidates=candidates,
        )

    if len(normalized_source) <= resolved_max_chars:
        return Stage2DocumentContext(
            source_text=normalized_source,
            generation_text=normalized_source,
            was_trimmed=False,
            source_char_count=len(normalized_source),
            generation_char_count=len(normalized_source),
            chunk_candidates=candidates,
        )

    generation_text = build_stage2_reference_excerpt(
        document_text=normalized_source,
        question=question,
        max_chars=resolved_max_chars,
    )
    if not generation_text:
        generation_text = normalized_source[:resolved_max_chars].strip()

    return Stage2DocumentContext(
        source_text=normalized_source,
        generation_text=generation_text,
        was_trimmed=True,
        source_char_count=len(normalized_source),
        generation_char_count=len(generation_text),
        chunk_candidates=candidates,
    )

