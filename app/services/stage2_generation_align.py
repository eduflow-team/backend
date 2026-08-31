"""Stage 2 Langflow 생성 결과를 교사 요청값에 맞게 정렬한다."""

from __future__ import annotations

import re
from difflib import SequenceMatcher

from app.core.config import settings
from app.schemas.stage2_generation import (
    Stage2GeneratedErrorDraft,
    Stage2LangflowGenerationResult,
)
from app.services.grading.highlight_grader import _normalize, _overlap_score

_META_LINE_PATTERN = re.compile(
    r"^(정상\s*(설명|마무리)|도입과\s*정상\s*설명).*$",
    re.IGNORECASE | re.MULTILINE,
)
_SLOT_MARKER_PATTERN = re.compile(r"\[\[\s*ERROR_?\d+\s*\]\]", re.IGNORECASE)
_LEAKAGE_PHRASES = (
    "사실과 다릅니다",
    "정확하지 않습니다",
    "사실이 아닙니다",
    "잘못된 정보입니다",
    "오류입니다",
    "오류예요",
    "잘못 이해",
    "헷갈리",
    "혼동이 있",
    "알려져 있지만, 사실",
    "알려져 있지만 사실",
    "하지만 사실",
    "오해되는 경우",
    "틀린 내용",
)
_FAKE_EVIDENCE_PATTERN = re.compile(
    r"^(본문\s*\d+쪽|수능\s*기본|2027학년도\s*EBS).*$",
    re.IGNORECASE,
)


def align_stage2_generation_result(
    result: Stage2LangflowGenerationResult,
    *,
    document_text: str = "",
    candidate_chunk_texts: list[str] | None = None,
    hallucination_types: list[str],
    expected_error_count: int,
) -> Stage2LangflowGenerationResult:
    """오류 개수·유형·본문·근거를 교사 요청값에 맞게 보정한다.

    Planner/Formatter가 개수·유형을 어긋내도 검증 전에 1차 정렬한다.
    오류 항목 자체가 부족한 경우는 그대로 둔다.
    """
    allowed_types = [value.strip().upper() for value in hallucination_types if value.strip()]
    errors = list(result.generated_errors)
    chunk_texts = [text.strip() for text in (candidate_chunk_texts or []) if text.strip()]

    if expected_error_count > 0 and len(errors) > expected_error_count:
        errors = errors[:expected_error_count]

    if allowed_types:
        aligned: list[Stage2GeneratedErrorDraft] = []
        for index, error in enumerate(errors):
            assigned_type = (
                allowed_types[index]
                if index < len(allowed_types)
                else error.error_type
            )
            aligned.append(
                error.model_copy(update={"error_type": assigned_type}),
            )
        errors = aligned

    if document_text.strip():
        errors = [
            error.model_copy(
                update={
                    "evidence_sentence": _repair_evidence_sentence(
                        error,
                        document_text=document_text,
                        candidate_chunk_texts=chunk_texts,
                    ),
                },
            )
            for error in errors
        ]

    flawed_ai_response = _sanitize_flawed_ai_response(
        result.flawed_ai_response,
        errors,
    )
    flawed_ai_response = _dedupe_error_sentences_in_response(
        flawed_ai_response,
        errors,
    )
    flawed_ai_response = _strip_exposed_correct_sentences(
        flawed_ai_response,
        errors,
    )

    return result.model_copy(
        update={
            "flawed_ai_response": flawed_ai_response,
            "generated_errors": errors,
        },
    )


def _repair_evidence_sentence(
    error: Stage2GeneratedErrorDraft,
    *,
    document_text: str,
    candidate_chunk_texts: list[str],
) -> str:
    evidence = error.evidence_sentence.strip()
    if evidence and not _FAKE_EVIDENCE_PATTERN.match(evidence):
        snapped = _snap_evidence_to_document(evidence, document_text)
        if _text_exists_in_document(snapped, document_text):
            return snapped

    threshold = settings.STAGE2_LOCATION_THRESHOLD
    anchor = error.error_sentence.strip() or evidence or error.hallucination_reason
    pool: list[str] = []
    for source in (document_text, *candidate_chunk_texts):
        pool.extend(_document_sentence_candidates(source))
    pool = list(dict.fromkeys(candidate for candidate in pool if candidate.strip()))

    best_match = evidence
    best_score = 0.0
    for candidate in pool:
        score = max(
            _overlap_score(_normalize(anchor), _normalize(candidate)),
            _overlap_score(_normalize(evidence), _normalize(candidate)) if evidence else 0.0,
        )
        if score > best_score:
            best_score = score
            best_match = candidate

    if best_score >= threshold:
        return _snap_evidence_to_document(best_match, document_text)

    if pool:
        return _snap_evidence_to_document(pool[0], document_text)
    if evidence:
        return _snap_evidence_to_document(evidence, document_text)
    return evidence


def _text_exists_in_document(needle: str, document_text: str) -> bool:
    normalized_needle = _normalize(needle)
    normalized_document = _normalize(document_text)
    if not normalized_needle or not normalized_document:
        return False
    if normalized_needle in normalized_document:
        return True
    if needle.strip() and needle.strip() in document_text:
        return True
    compact_needle = _compact_text(needle)
    compact_document = _compact_text(document_text)
    if compact_needle and compact_needle in compact_document:
        return True
    return _overlap_score(normalized_needle, normalized_document) >= settings.STAGE2_LOCATION_THRESHOLD


def _sanitize_flawed_ai_response(
    flawed_ai_response: str,
    errors: list[Stage2GeneratedErrorDraft],
) -> str:
    text = (flawed_ai_response or "").strip()
    for index, error in enumerate(errors, start=1):
        sentence = error.error_sentence.strip()
        if not sentence:
            continue
        text = re.sub(
            rf"\[\[\s*ERROR_?{index}\s*\]\]",
            sentence,
            text,
            count=1,
            flags=re.IGNORECASE,
        )
    text = _SLOT_MARKER_PATTERN.sub("", text)
    text = _META_LINE_PATTERN.sub("", text)
    for phrase in _LEAKAGE_PHRASES:
        text = text.replace(phrase, "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _dedupe_error_sentences_in_response(
    flawed_ai_response: str,
    errors: list[Stage2GeneratedErrorDraft],
) -> str:
    text = flawed_ai_response
    threshold = settings.STAGE2_LOCATION_THRESHOLD

    for error in errors:
        sentence = error.error_sentence.strip()
        if not sentence:
            continue
        first_index = text.find(sentence)
        if first_index == -1:
            continue
        search_start = first_index + len(sentence)
        while True:
            duplicate_index = text.find(sentence, search_start)
            if duplicate_index == -1:
                break
            text = text[:duplicate_index] + text[duplicate_index + len(sentence) :]
            search_start = duplicate_index

    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", text)
        if sentence.strip()
    ]
    if not sentences:
        return text

    error_sentences = [error.error_sentence.strip() for error in errors if error.error_sentence.strip()]
    kept: list[str] = []
    for sentence in sentences:
        normalized_sentence = _normalize(sentence)
        is_duplicate = False
        for error_sentence in error_sentences:
            normalized_error = _normalize(error_sentence)
            if normalized_sentence == normalized_error:
                break
            if (
                normalized_error in normalized_sentence
                or SequenceMatcher(None, normalized_error, normalized_sentence).ratio()
                >= threshold
            ):
                is_duplicate = True
                break
        if not is_duplicate:
            kept.append(sentence)
    return "\n".join(kept) if "\n" in text else " ".join(kept)


def _strip_exposed_correct_sentences(
    flawed_ai_response: str,
    errors: list[Stage2GeneratedErrorDraft],
) -> str:
    threshold = settings.STAGE2_LOCATION_THRESHOLD
    sentences = [
        sentence.strip()
        for sentence in re.split(r"(?<=[.!?。！？])\s+|\n+", flawed_ai_response)
        if sentence.strip()
    ]
    if not sentences:
        return flawed_ai_response

    kept: list[str] = []
    for sentence in sentences:
        normalized_sentence = _normalize(sentence)
        drop = False
        for error in errors:
            correct_sentence = error.correct_sentence.strip()
            error_sentence = error.error_sentence.strip()
            if not correct_sentence:
                continue
            normalized_correct = _normalize(correct_sentence)
            normalized_error = _normalize(error_sentence)
            if normalized_sentence == normalized_error or (
                error_sentence and error_sentence in sentence
            ):
                drop = False
                break
            if (
                normalized_correct in normalized_sentence
                or SequenceMatcher(None, normalized_correct, normalized_sentence).ratio()
                >= threshold
            ):
                drop = True
                break
        if not drop:
            kept.append(sentence)

    if not kept:
        return flawed_ai_response
    return "\n".join(kept) if "\n" in flawed_ai_response else " ".join(kept)


def _snap_evidence_to_document(evidence_sentence: str, document_text: str) -> str:
    evidence = evidence_sentence.strip()
    document = document_text.strip()
    if not evidence or not document:
        return evidence

    if evidence in document:
        return evidence

    compact_evidence = _compact_text(evidence)
    compact_document = _compact_text(document)
    if compact_evidence and compact_evidence in compact_document:
        return _extract_compact_match_span(evidence, document) or evidence

    threshold = settings.STAGE2_LOCATION_THRESHOLD
    best_match = evidence
    best_score = _overlap_score(_normalize(evidence), _normalize(document))
    for candidate in _document_sentence_candidates(document):
        score = _overlap_score(_normalize(evidence), _normalize(candidate))
        if score > best_score:
            best_score = score
            best_match = candidate
    if best_score >= threshold:
        return best_match
    return evidence


def _document_sentence_candidates(document_text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。])\s+|\n+", document_text)
    candidates = [part.strip() for part in parts if len(part.strip()) >= 8]
    for index in range(len(parts) - 1):
        joined = f"{parts[index].strip()} {parts[index + 1].strip()}".strip()
        if len(joined) >= 8:
            candidates.append(joined)
    return list(dict.fromkeys(candidates))


def _extract_compact_match_span(needle: str, document_text: str) -> str | None:
    compact_needle = _compact_text(needle)
    if not compact_needle:
        return None

    best_span: str | None = None
    best_length = 0
    normalized_lines = document_text.splitlines()
    for line_count in range(1, 4):
        for start in range(len(normalized_lines)):
            chunk = "\n".join(normalized_lines[start : start + line_count]).strip()
            if not chunk:
                continue
            compact_chunk = _compact_text(chunk)
            if compact_needle in compact_chunk and len(chunk) > best_length:
                best_span = chunk
                best_length = len(chunk)
    return best_span


def _compact_text(text: str) -> str:
    return re.sub(r"\s+", "", (text or "").strip().lower())
