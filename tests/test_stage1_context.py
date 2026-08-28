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
        lambda pool, k: ["노이즈A", "노이즈B", "노이즈C", "노이즈D"][:k],
    )
    out = wrap_stage1_langflow_context("실제청크_토지조사사업", mode="WEAK")
    assert "[내부모드: WEAK]" in out
    assert "실제청크_토지조사사업" not in out
    assert "노이즈A" in out
    assert "사실처럼 단정" in out or "고유명사" in out


def test_wrap_strong_no_noise():
    out = wrap_stage1_langflow_context("실제청크", mode="STRONG")
    assert "[내부모드: STRONG]" in out
    assert "실제청크" in out
    assert "노이즈" not in out
    assert "절대 금지" in out


def test_enforce_weak_replaces_sane_answer(monkeypatch):
    from app.services.stage1_context import enforce_stage1_weak_hallucination

    monkeypatch.setattr(
        "app.services.stage1_context.settings.STAGE1_WEAK_FORCE_HALLUCINATION",
        True,
    )
    monkeypatch.setattr(
        "app.services.stage1_context.random.choice",
        lambda seq: seq[0],
    )
    noises = [
        "1910년부터 1918년까지 일제는 한글 보급 사업을 전국적으로 실시하였다.",
        "일제는 토지 조사 대신 철도 국유화만으로 조선 경제를 지배하려 하였다.",
    ]
    out = enforce_stage1_weak_hallucination(
        "자료를 보면 토지와 관련한 제도를 더 살펴보시면 좋을 것 같아요.",
        planted_noises=noises,
        correct_answer="동양척식주식회사",
    )
    assert "한글 보급" in out or "철도 국유화" in out
    assert "동양척식" not in out


def test_enforce_weak_keeps_answer_with_bait(monkeypatch):
    from app.services.stage1_context import enforce_stage1_weak_hallucination

    monkeypatch.setattr(
        "app.services.stage1_context.settings.STAGE1_WEAK_FORCE_HALLUCINATION",
        True,
    )
    noises = [
        "이른바 산미 증식 계획이 1910년에 시작되어 토지 소유권을 조선인에게 되돌려 주었다.",
    ]
    text = "자료를 보면 산미 증식과 관련된 이야기가 나옵니다. 이 키워드를 힌트로 보세요."
    out = enforce_stage1_weak_hallucination(
        text,
        planted_noises=noises,
        correct_answer="동양척식주식회사",
    )
    assert out == text


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
    assert out[0].endswith(("다.", "다", "다 "))
    assert not out[0].endswith("…")


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
    assert not out[0].endswith("…")


def test_format_topk_rejects_particle_fragment_and_expands():
    from app.services.stage1_context import format_stage1_topk_sentences

    doc = (
        "일부 지역에서는 일본의 방침에 따르지 않은 경우도 있었다. "
        "그러나 대부분의 농민은 토지를 빼앗겼다."
    )
    fragment = "에 따르지 않은 경우도 있었다."
    out = format_stage1_topk_sentences([fragment], doc)
    assert len(out) == 1
    assert not out[0].startswith("에 ")
    assert "따르지 않은 경우도 있었다" in out[0]
    assert "일본" in out[0] or "방침" in out[0]


def test_format_topk_rejects_ellipsis_ocr_stub():
    from app.services.stage1_context import format_stage1_topk_sentences

    doc = (
        "모든 사회적 폐습을 타파하고 민주주의 제도를 수립하여 국민의 권리를 보장하였다. "
        "이것이 3·1 운동의 정신이었다."
    )
    stub = "모든 사회적 폐습을 타파하고 민주주의 제 AES 수립하여"
    out = format_stage1_topk_sentences([stub], doc)
    assert len(out) == 1
    assert "AES" not in out[0]
    assert "민주주의" in out[0]
    assert not out[0].endswith("…")
    assert out[0].endswith(("다.", "다"))


def test_format_topk_drops_bullet_and_ocr_caps_junk():
    from app.services.stage1_context import format_stage1_topk_sentences

    doc = (
        "창씨개명으로 너희들의 새 이름은 동사무소에 이미 등록되어 있을 것이다. "
        "일제 강점기의 사진, 노래, 신문 기사, 문학 작품, 수기 등의 자료를 통해 "
        "당시 우리 민족의 생활 모습을 알아보자."
    )
    junk = (
        "· 일제 강점기의 사진, 노래, 신문 기사, 문학 작품, 수기 등의 ASS 통해 "
        "당시 우리 민족의 생활 모습을 알아보자."
    )
    out = format_stage1_topk_sentences(
        ["너희들의 새 이름은 동사무소에 이미 등록되어 있을 것이다", junk],
        doc,
    )
    assert len(out) >= 1
    assert all(not s.startswith("·") for s in out)
    assert all("ASS" not in s for s in out)
    assert all("등의 통해" not in s for s in out)
    # 깨끗한 원문 문장으로 대체되었는지
    joined = " ".join(out)
    assert "동사무소" in joined or "자료를 통해" in joined
