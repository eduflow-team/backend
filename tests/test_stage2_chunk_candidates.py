"""Tests for Stage 2 document chunk candidate generation."""

from __future__ import annotations

from app.services.stage2_chunk_candidates import build_stage2_chunk_candidates

BASELINE_DOCUMENT = (
    "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.\n"
    "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계이고, 측우기는 비의 양을 재는 기구입니다."
)
BASELINE_QUESTION = "장영실의 발명품에 대해 설명해줘."


def test_build_candidates_from_baseline_document() -> None:
    candidates = build_stage2_chunk_candidates(
        document_text=BASELINE_DOCUMENT,
        question=BASELINE_QUESTION,
    )

    assert 1 <= len(candidates) <= 5
    assert all(candidate.chunk_id.startswith("chunk-") for candidate in candidates)
    assert all(candidate.source_index >= 0 for candidate in candidates)
    assert all(
        candidate.selection_bucket in {"TOP_RELEVANCE", "DIVERSE_CONTEXT"}
        for candidate in candidates
    )
    assert candidates[0].relevance_score >= candidates[-1].relevance_score


def test_empty_document_returns_no_candidates() -> None:
    assert build_stage2_chunk_candidates(document_text="   ", question=BASELINE_QUESTION) == []


def test_short_evidence_is_merged_instead_of_removed() -> None:
    short_evidence = "측우기는 비를 잰다."
    document = short_evidence + "\n\n\n\n" + BASELINE_DOCUMENT
    candidates = build_stage2_chunk_candidates(
        document_text=document,
        question=BASELINE_QUESTION,
        chunk_size=80,
        min_chunk_chars=30,
    )
    assert candidates
    assert any(short_evidence in candidate.text for candidate in candidates)


def test_long_document_limits_candidate_count_and_total_chars() -> None:
    paragraphs = [
        f"주제 {index}에 대한 설명 문단입니다. 장영실과 발명품에 대한 내용을 담고 있습니다."
        for index in range(30)
    ]
    document = "\n\n".join(paragraphs)

    candidates = build_stage2_chunk_candidates(
        document_text=document,
        question=BASELINE_QUESTION,
        chunk_size=120,
        max_candidates=5,
        max_total_chars=800,
    )

    assert len(candidates) <= 5
    assert sum(len(candidate.text) for candidate in candidates) <= 800


def test_same_input_produces_same_candidates() -> None:
    first = build_stage2_chunk_candidates(
        document_text=BASELINE_DOCUMENT,
        question=BASELINE_QUESTION,
    )
    second = build_stage2_chunk_candidates(
        document_text=BASELINE_DOCUMENT,
        question=BASELINE_QUESTION,
    )
    assert first == second


def test_question_relevance_orders_candidates() -> None:
    document = (
        "조선시대 왕실의 생활과 궁궐 문화에 대한 상세한 설명입니다.\n\n"
        "장영실은 자격루와 측우기를 발명한 과학자이며 세종 시대에 활동했습니다.\n\n"
        "조선의 농업과 풍습 및 백성들의 생활상에 대한 상세한 설명입니다."
    )
    candidates = build_stage2_chunk_candidates(
        document_text=document,
        question="장영실의 발명품",
        chunk_size=50,
        min_chunk_chars=20,
        max_candidates=3,
    )

    assert candidates
    assert "장영실" in candidates[0].text
    assert candidates[0].relevance_score >= candidates[-1].relevance_score


def test_sentence_boundaries_are_preserved() -> None:
    first = "첫 번째 문장은 자격루에 관한 충분히 긴 설명입니다."
    second = "두 번째 문장은 측우기에 관한 충분히 긴 설명입니다."
    candidates = build_stage2_chunk_candidates(
        document_text=f"{first} {second}",
        question="자격루",
        chunk_size=50,
        min_chunk_chars=10,
        max_candidates=5,
    )

    assert candidates
    assert any(candidate.text == first for candidate in candidates)
    assert any(candidate.text == second for candidate in candidates)


def test_diverse_context_candidates_cover_distant_source_chunks() -> None:
    paragraphs = [
        f"장영실 발명품과 관련된 후보 문단 {index}이며 서로 다른 상세 내용을 포함합니다."
        for index in range(12)
    ]
    candidates = build_stage2_chunk_candidates(
        document_text="\n\n".join(paragraphs),
        question="장영실 발명품",
        chunk_size=50,
        min_chunk_chars=20,
        max_candidates=5,
    )

    diverse = [
        candidate
        for candidate in candidates
        if candidate.selection_bucket == "DIVERSE_CONTEXT"
    ]
    assert diverse
    assert max(candidate.source_index for candidate in diverse) >= 6


def test_numeric_source_index_breaks_equal_score_ties() -> None:
    paragraphs = [
        f"서로 다른 일반 역사 설명 문단이며 식별 번호는 {index}입니다."
        for index in range(12)
    ]
    candidates = build_stage2_chunk_candidates(
        document_text="\n\n".join(paragraphs),
        question="관련 없는 질문",
        chunk_size=50,
        min_chunk_chars=20,
        max_candidates=2,
    )

    assert [candidate.source_index for candidate in candidates] == [0, 1]


def test_total_char_limit_applies_to_first_candidate() -> None:
    candidates = build_stage2_chunk_candidates(
        document_text=BASELINE_DOCUMENT,
        question=BASELINE_QUESTION,
        max_total_chars=10,
    )
    assert candidates == []
