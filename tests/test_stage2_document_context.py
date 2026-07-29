"""Tests for Stage 2 document context excerpt resolution."""

from __future__ import annotations

from app.services.stage2_document_context import resolve_stage2_document_context


def test_short_document_passthrough_without_trim() -> None:
    source = (
        "장영실은 세종 대에 자격루와 측우기를 발명한 조선시대 최고의 과학자입니다.\n"
        "자격루는 물의 흐름을 이용해 시간을 알리는 자동 물시계입니다."
    )

    context = resolve_stage2_document_context(
        source_text=source,
        question="장영실의 발명품에 대해 설명해줘.",
        max_generation_chars=6000,
    )

    assert context.was_trimmed is False
    assert context.generation_text == source
    assert context.source_char_count == len(source)
    assert context.chunk_candidates


def test_long_document_uses_question_relevant_excerpt() -> None:
    paragraphs = [
        (
            f"제{index}단원 보충 설명입니다. 장영실과 자격루, 측우기, 조선시대 과학 기술 "
            f"발전에 대한 내용을 담고 있습니다. 학생들이 참고할 수 있는 배경 지식입니다."
        )
        for index in range(1, 41)
    ]
    source = "\n\n".join(paragraphs)
    question = "장영실의 자격루와 측우기 발명에 대해 설명해줘."

    context = resolve_stage2_document_context(
        source_text=source,
        question=question,
        max_generation_chars=1200,
    )

    assert context.was_trimmed is True
    assert len(context.generation_text) <= 1200
    assert len(context.generation_text) < len(source)
    assert "장영실" in context.generation_text


def test_long_document_excerpt_preserves_reading_order() -> None:
    source = "\n\n".join(
        [
            "고려 시대 불교 문화와 사창 경제의 배경을 설명하는 일반 역사 단락입니다.",
            "조선 초기 사대교린 정책의 개요를 다루는 배경 설명 단락입니다.",
            "세 번째 단락에서 장영실이 자격루와 측우기를 발명했다고 설명합니다.",
            "네 번째 단락은 측우기의 구조와 측정 원리를 설명합니다.",
            "다섯 번째 단락은 조선 왕실의 과학 지원 정책을 설명합니다.",
        ]
    )

    context = resolve_stage2_document_context(
        source_text=source,
        question="장영실의 자격루와 측우기에 대해 설명해줘.",
        max_generation_chars=150,
    )

    assert context.was_trimmed is True
    assert "고려 시대" not in context.generation_text
    assert "사대교린" not in context.generation_text
    third_index = context.generation_text.find("세 번째 단락")
    fourth_index = context.generation_text.find("네 번째 단락")
    assert third_index != -1
    assert fourth_index != -1
    assert third_index < fourth_index


def test_long_document_excerpt_skips_low_relevance_front_matter() -> None:
    source = "\n\n".join(
        [
            "출판사 안내와 저작권 표기가 포함된 앞표지 영역입니다.",
            "찾아보기와 색인 목록이 제시된 부록 안내입니다.",
            "명·청 교역은 동아시아 해상 교역망의 확대와 은 유통과 관련됩니다.",
            "청의 해금 정책과 교역 제한 속에서도 교역은 지속되었습니다.",
        ]
    )

    context = resolve_stage2_document_context(
        source_text=source,
        question="명·청 교역과 관련된 내용을 설명해줘.",
        max_generation_chars=80,
    )

    assert context.was_trimmed is True
    assert "출판사 안내" not in context.generation_text
    assert "찾아보기" not in context.generation_text
    assert "명·청 교역" in context.generation_text


def test_empty_document_returns_empty_generation_text() -> None:
    context = resolve_stage2_document_context(
        source_text="   ",
        question="질문",
        max_generation_chars=6000,
    )

    assert context.generation_text == ""
    assert context.was_trimmed is False
    assert context.chunk_candidates == []
