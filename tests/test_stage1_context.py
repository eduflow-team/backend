"""Stage1 WEAK/STRONG context 래핑 단위 테스트."""

from app.services.stage1_context import (
    is_stage1_weak_retrieval,
    redact_stage1_answer_leak,
    wrap_stage1_langflow_context,
)


def test_weak_when_default_weak_params():
    assert is_stage1_weak_retrieval(
        approx_context_chars=2000,
        vector_search_score=0.9,
        chunk_size=50,
        top_k=2,
    )


def test_strong_when_chunk_raised_even_if_score_low():
    # 파라미터를 올렸으면 유사도가 낮아도 STRONG (실제 청크 사용)
    assert not is_stage1_weak_retrieval(
        approx_context_chars=100,
        vector_search_score=0.1,
        chunk_size=3000,
        top_k=5,
    )


def test_strong_when_top_k_raised():
    assert not is_stage1_weak_retrieval(
        approx_context_chars=100,
        vector_search_score=0.1,
        chunk_size=50,
        top_k=5,
    )


def test_weak_only_when_both_params_low():
    assert is_stage1_weak_retrieval(
        approx_context_chars=100,
        vector_search_score=0.1,
        chunk_size=50,
        top_k=2,
    )


def test_wrap_weak_excludes_real_chunks(monkeypatch):
    monkeypatch.setattr(
        "app.services.stage1_context.settings.STAGE1_WEAK_NOISE_ENABLED",
        True,
    )
    monkeypatch.setattr(
        "app.services.stage1_context.random.sample",
        lambda pool, k: ["노이즈A", "노이즈B", "노이즈C"][:k],
    )
    out = wrap_stage1_langflow_context("실제청크_토지조사사업", mode="WEAK")
    assert "[내부모드: WEAK]" in out
    assert "실제청크_토지조사사업" not in out
    assert "노이즈A" in out
    assert "사실처럼 단정" in out


def test_wrap_strong_no_noise():
    out = wrap_stage1_langflow_context("실제청크", mode="STRONG")
    assert "[내부모드: STRONG]" in out
    assert "실제청크" in out
    assert "노이즈" not in out
    assert "절대 금지" in out


def test_redact_exact_answer():
    out = redact_stage1_answer_leak(
        "정답은 동양척식주식회사입니다. 일제가 토지를 수탈했습니다.",
        "동양척식주식회사",
    )
    assert "동양척식주식회사" not in out
    assert "□□□" in out or "정답 자체는" in out


def test_redact_answer_with_spaces():
    out = redact_stage1_answer_leak(
        "이건 동양 척식 주식회사가 관련되어 있어요.",
        "동양척식주식회사",
    )
    assert "동양척식" not in out.replace(" ", "")
    assert "□□□" in out or "정답 자체는" in out


def test_redact_passthrough_when_no_leak():
    text = "일제 강점기 토지 수탈과 관련된 기관을 청크에서 찾아보세요."
    assert redact_stage1_answer_leak(text, "동양척식주식회사") == text


def test_format_topk_expands_to_sentence():
    from app.services.stage1_context import format_stage1_topk_sentences

    doc = (
        "무단 통치 시기 조선 총독부는 토지 조사 사업을 실시했다. "
        "총독부는 이렇게 약탈한 토지를 동양 척식 주식 회사 등 일본인이 경영하는 "
        "토지 회사나 지주에게 헐값으로 불하하였다. "
        "그 결과 많은 농민이 토지를 잃었다."
    )
    raw_chunk = "약탈한 토지를 동양 척식 주식 회사 등"
    out = format_stage1_topk_sentences([raw_chunk], doc)
    assert len(out) == 1
    assert "동양 척식" in out[0]
    assert "불하" in out[0] or "토지 회사" in out[0]
    assert out[0].endswith(("다.", "다"))


def test_format_topk_prefers_clean_sentence_over_ocr_fragment():
    from app.services.stage1_context import format_stage1_topk_sentences

    doc = (
        "일제는 토지를 약탈하였다. "
        "이른바 토지 조사 사업(1910~1918)을 실시하여 소유권을 정리하였다. "
        "그 결과 한국 농민은 큰 피해를 입었다."
    )
    messy = "의 SHS ALS 후, 이른바 「토지 조사 사업(1910~1918)' 을 실시하여 우"
    out = format_stage1_topk_sentences([messy], doc)
    assert len(out) == 1
    assert "SHS" not in out[0]
    assert "토지 조사 사업" in out[0]
    assert "실시" in out[0]
