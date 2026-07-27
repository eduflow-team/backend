"""Stage 2 PDF 문서 청크 후보 생성."""

from __future__ import annotations

from dataclasses import dataclass

from app.core.config import settings
from app.services.embedding_service import split_text_into_chunks
from app.services.grading.highlight_grader import _normalize, _overlap_score


@dataclass(frozen=True)
class Stage2ChunkCandidate:
    chunk_id: str
    text: str
    relevance_score: float


def build_stage2_chunk_candidates(
    *,
    document_text: str,
    question: str,
    chunk_size: int | None = None,
    min_chunk_chars: int | None = None,
    max_candidates: int | None = None,
    max_total_chars: int | None = None,
) -> list[Stage2ChunkCandidate]:
    """Stage 2 PDF 본문에서 Langflow에 전달할 청크 후보를 생성한다."""
    resolved_chunk_size = (
        settings.STAGE2_CHUNK_SIZE if chunk_size is None else chunk_size
    )
    resolved_min_chars = (
        settings.STAGE2_MIN_CHUNK_CHARS if min_chunk_chars is None else min_chunk_chars
    )
    resolved_max_candidates = (
        settings.STAGE2_MAX_CHUNK_CANDIDATES
        if max_candidates is None
        else max_candidates
    )
    resolved_max_total_chars = (
        settings.STAGE2_MAX_CANDIDATE_TOTAL_CHARS
        if max_total_chars is None
        else max_total_chars
    )

    chunks = split_text_into_chunks(document_text, resolved_chunk_size)
    filtered = [chunk for chunk in chunks if len(chunk.strip()) >= resolved_min_chars]
    if not filtered:
        return []

    normalized_question = _normalize(question)
    scored = sorted(
        (
            Stage2ChunkCandidate(
                chunk_id=f"chunk-{index}",
                text=chunk,
                relevance_score=_score_chunk_relevance(normalized_question, chunk),
            )
            for index, chunk in enumerate(filtered)
        ),
        key=lambda candidate: (-candidate.relevance_score, candidate.chunk_id),
    )

    selected: list[Stage2ChunkCandidate] = []
    total_chars = 0
    for candidate in scored:
        if len(selected) >= resolved_max_candidates:
            break
        next_total = total_chars + len(candidate.text)
        if selected and next_total > resolved_max_total_chars:
            break
        selected.append(candidate)
        total_chars = next_total

    return selected


def _score_chunk_relevance(normalized_question: str, chunk_text: str) -> float:
    normalized_chunk = _normalize(chunk_text)
    if not normalized_question or not normalized_chunk:
        return 0.0
    return _overlap_score(normalized_question, normalized_chunk)
