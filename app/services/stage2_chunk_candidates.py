"""Stage 2 PDF 문서 청크 후보 생성."""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.core.config import settings
from app.services.embedding_service import split_text_into_chunks
from app.services.grading.highlight_grader import _normalize, _overlap_score


@dataclass(frozen=True)
class Stage2ChunkCandidate:
    chunk_id: str
    source_index: int
    text: str
    relevance_score: float
    selection_bucket: str


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

    chunks = _split_stage2_document(document_text, resolved_chunk_size)
    chunks = _merge_short_chunks(
        chunks,
        min_chunk_chars=resolved_min_chars,
    )
    if not chunks:
        return []

    normalized_question = _normalize(question)
    ranked = sorted(
        [
            Stage2ChunkCandidate(
                chunk_id=f"chunk-{index}",
                source_index=index,
                text=chunk,
                relevance_score=_score_chunk_relevance(normalized_question, chunk),
                selection_bucket="UNSELECTED",
            )
            for index, chunk in enumerate(chunks)
        ],
        key=lambda candidate: (-candidate.relevance_score, candidate.source_index),
    )
    selected_pool = _select_diverse_candidates(
        ranked,
        max_candidates=resolved_max_candidates,
    )

    selected: list[Stage2ChunkCandidate] = []
    total_chars = 0
    for candidate in selected_pool:
        next_total = total_chars + len(candidate.text)
        if next_total > resolved_max_total_chars:
            continue
        selected.append(candidate)
        total_chars = next_total

    return selected


def _score_chunk_relevance(normalized_question: str, chunk_text: str) -> float:
    """가벼운 lexical 휴리스틱 점수이며 의미 유사도를 보장하지 않는다."""
    normalized_chunk = _normalize(chunk_text)
    if not normalized_question or not normalized_chunk:
        return 0.0
    return _overlap_score(normalized_question, normalized_chunk)


def _split_stage2_document(document_text: str, chunk_size: int) -> list[str]:
    """PDF 줄바꿈을 정리하고 가능한 범위에서 문장 경계를 보존해 청킹한다."""
    normalized = re.sub(r"\r\n?", "\n", document_text).strip()
    if not normalized:
        return []

    sentence_units = [
        unit.strip()
        for unit in re.split(r"(?<=[.!?。！？])\s+|\n+", normalized)
        if unit.strip()
    ]
    sentence_separated = "\n\n".join(sentence_units)
    return split_text_into_chunks(sentence_separated, chunk_size)


def _merge_short_chunks(
    chunks: list[str],
    *,
    min_chunk_chars: int,
) -> list[str]:
    """짧은 근거를 버리지 않고 인접 청크와 병합한다."""
    if not chunks:
        return []

    merged: list[str] = []
    pending = ""
    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            continue
        if len(stripped) < min_chunk_chars:
            if merged:
                merged[-1] = f"{merged[-1]}\n\n{stripped}"
            else:
                pending = f"{pending}\n\n{stripped}".strip()
            continue
        if pending:
            stripped = f"{pending}\n\n{stripped}"
            pending = ""
        merged.append(stripped)

    if pending:
        if merged:
            merged[-1] = f"{merged[-1]}\n\n{pending}"
        else:
            merged.append(pending)
    return merged


def _select_diverse_candidates(
    ranked: list[Stage2ChunkCandidate],
    *,
    max_candidates: int,
) -> list[Stage2ChunkCandidate]:
    """상위 근거 후보와 문서 전반의 context 후보를 함께 선택한다."""
    if max_candidates <= 0 or not ranked:
        return []

    limit = min(max_candidates, len(ranked))
    top_count = min(2, limit)
    selected = [
        _with_bucket(candidate, "TOP_RELEVANCE")
        for candidate in ranked[:top_count]
    ]

    remaining = ranked[top_count:]
    needed = limit - len(selected)
    if needed <= 0:
        return selected
    if len(remaining) <= needed:
        selected.extend(
            _with_bucket(candidate, "DIVERSE_CONTEXT")
            for candidate in remaining
        )
        return selected

    positions = {
        min(len(remaining) - 1, ((index + 1) * len(remaining)) // (needed + 1))
        for index in range(needed)
    }
    for position in sorted(positions):
        selected.append(_with_bucket(remaining[position], "DIVERSE_CONTEXT"))
    return selected


def _with_bucket(
    candidate: Stage2ChunkCandidate,
    bucket: str,
) -> Stage2ChunkCandidate:
    return Stage2ChunkCandidate(
        chunk_id=candidate.chunk_id,
        source_index=candidate.source_index,
        text=candidate.text,
        relevance_score=candidate.relevance_score,
        selection_bucket=bucket,
    )


def build_stage2_reference_excerpt(
    *,
    document_text: str,
    question: str,
    max_chars: int,
    chunk_size: int | None = None,
    min_chunk_chars: int | None = None,
) -> str:
    """질문과 관련 높은 청크를 우선 선택해 학생용 발췌문을 만든다.

    선택된 청크는 문서 읽기 순서(source_index)로 이어 붙인다.
    """
    if max_chars <= 0:
        return ""

    resolved_chunk_size = (
        settings.STAGE2_CHUNK_SIZE if chunk_size is None else chunk_size
    )
    resolved_min_chars = (
        settings.STAGE2_MIN_CHUNK_CHARS if min_chunk_chars is None else min_chunk_chars
    )

    units = _split_stage2_excerpt_units(
        document_text,
        chunk_size=resolved_chunk_size,
        min_chunk_chars=resolved_min_chars,
    )
    if not units:
        return ""

    normalized_question = _normalize(question)
    scored = [
        Stage2ChunkCandidate(
            chunk_id=f"chunk-{index}",
            source_index=index,
            text=unit,
            relevance_score=_score_chunk_relevance(normalized_question, unit),
            selection_bucket="EXCERPT",
        )
        for index, unit in enumerate(units)
    ]

    ranked = sorted(
        scored,
        key=lambda candidate: (-candidate.relevance_score, candidate.source_index),
    )
    top_score = ranked[0].relevance_score if ranked else 0.0
    min_score = max(top_score - 0.2, top_score * 0.55) if top_score > 0 else 0.0
    eligible = [
        candidate
        for candidate in ranked
        if candidate.relevance_score >= min_score
    ]

    selected: list[Stage2ChunkCandidate] = []
    total_chars = 0
    for candidate in eligible:
        text = candidate.text.strip()
        if not text:
            continue

        separator_len = 2 if selected else 0
        next_total = total_chars + separator_len + len(text)
        if next_total > max_chars:
            continue

        selected.append(candidate)
        total_chars = next_total

    if not selected and ranked:
        top = ranked[0]
        selected = [
            Stage2ChunkCandidate(
                chunk_id=top.chunk_id,
                source_index=top.source_index,
                text=top.text.strip()[:max_chars].rstrip(),
                relevance_score=top.relevance_score,
                selection_bucket=top.selection_bucket,
            )
        ]

    ordered = sorted(selected, key=lambda candidate: candidate.source_index)
    return "\n\n".join(candidate.text.strip() for candidate in ordered).strip()


def _split_stage2_excerpt_units(
    document_text: str,
    *,
    chunk_size: int,
    min_chunk_chars: int,
) -> list[str]:
    """발췌문 선택용 단위를 만든다. 단락은 병합하지 않고 개별 점수화한다."""
    normalized = re.sub(r"\r\n?", "\n", document_text).strip()
    if not normalized:
        return []

    paragraphs = [p.strip() for p in re.split(r"\n{2,}", normalized) if p.strip()]
    units: list[str] = []
    for paragraph in paragraphs:
        if len(paragraph) <= chunk_size:
            units.append(paragraph)
            continue

        units.extend(
            _merge_short_chunks(
                _split_stage2_document(paragraph, chunk_size),
                min_chunk_chars=min_chunk_chars,
            )
        )
    return units
