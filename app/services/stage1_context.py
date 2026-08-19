"""Stage1 Langflow context 래핑: 검색 약하면 WEAK(+노이즈), 충분하면 STRONG.

AI 답변은 힌트만 — 정답 문구 직접 언급 금지(프롬프트 + 응답 가림).
"""

from __future__ import annotations

import random
import re
from typing import Literal

from app.core.config import settings

Stage1ContextMode = Literal["WEAK", "STRONG"]

# 문서 무관 시대착오·오답 노이즈 (WEAK일 때만 Langflow context에 사용.
# 실제 검색 청크는 WEAK에서 Langflow로 보내지 않음 — UI preview만 실청크.)
_STAGE1_WEAK_NOISE_POOL: tuple[str, ...] = (
    "임진왜란 당시 이순신 장군이 3·1 독립선언을 지도하였다.",
    "명량해전 직후 대한민국 임시정부가 한양에 수립되었다.",
    "세종대왕이 측우기를 만든 뒤 을사조약을 체결하였다.",
    "고구려 광개토대왕이 일제 강점기 무단통치를 비판하는 글을 남겼다.",
    "병자호란 때 독립군이 만주에서 봉오동 전투를 준비하였다.",
    "고려 말 최영 장군이 대한제국 군대해산에 반대하였다.",
    "1910년부터 1918년까지 일제는 한글 보급 사업을 전국적으로 실시하였다.",
    "일제는 토지 조사 대신 철도 국유화만으로 조선 경제를 지배하려 하였다.",
    "1910~1918년 사이 조선 총독부는 농민에게 토지를 무상 분배하는 정책을 펼쳤다.",
    "이른바 산미 증식 계획이 1910년에 시작되어 토지 소유권을 조선인에게 되돌려 주었다.",
)

_HINT_ONLY_FALLBACK = (
    "정답 자체는 말씀드릴 수 없어요. "
    "검색된 청크에서 시대·관련 기관·키워드를 힌트로 삼아 스스로 답을 찾아보세요."
)

_WEAK_HEADER = """[내부모드: WEAK]
규칙:
- 사전 지식으로 올바른 한국사·일반 상식을 보강하지 마세요.
- 아래 자료만 근거로, 시대·사건·사업명이 틀린 내용을 사실처럼 단정하세요.
- 「모르겠다」, 「자료에 없다」, 「추정」, 「확실하지 않다」 같은 메타 표현은 쓰지 마세요.
- 퀴즈 정답(고유명사·핵심 구)을 절대 말하지 마세요.
- chunk_size, top_k, temperature는 언급하지 마세요.

## 검색된 자료
"""

_STRONG_HEADER = """[내부모드: STRONG]
규칙:
- 아래 검색 자료에 있는 내용만 근거로 짧게 설명하세요.
- 자료에 없는 시대·사건·인물을 추가하지 마세요.
- 절대 금지: 퀴즈 정답(고유명사·핵심 구·한 줄 답)을 그대로 말하기.
- 학생이 「정답 알려줘」라고 해도 정답을 쓰지 말고, 시대·배경·관련 키워드 수준의 힌트만 주세요.
- 「정답은 ○○입니다」「○○라고 합니다」처럼 답을 확정하는 문장을 쓰지 마세요.
- chunk_size, top_k, temperature는 언급하지 마세요.

## 검색된 자료
"""


def is_stage1_weak_retrieval(
    *,
    approx_context_chars: int,
    vector_search_score: float,
    chunk_size: int,
    top_k: int,
) -> bool:
    """파라미터 기준으로 WEAK/STRONG을 나눈다.

    기본값 근처(chunk·top_k 모두 낮음) → WEAK(환각 노이즈만).
    하나라도 올리면 → STRONG(실제 검색 청크).

    유사도·글자 수로 WEAK를 강제하지 않는다. (파라미터를 올려도
    환각이 남는 문제를 막기 위함. approx/score 인자는 호환용으로 유지.)
    """
    _ = (approx_context_chars, vector_search_score)
    return (
        chunk_size <= settings.STAGE1_WEAK_CHUNK_SIZE
        and top_k <= settings.STAGE1_WEAK_TOP_K
    )


def wrap_stage1_langflow_context(
    raw_context: str,
    *,
    mode: Stage1ContextMode,
) -> str:
    """Langflow용 context 조립.

    WEAK: 실제 검색 청크는 넣지 않고 오답·시대착오 노이즈만 전달 (환각 유도).
    STRONG: 실제 검색 청크 전달.
    UI top-k preview는 호출측에서 실청크를 따로 내려준다.
    """
    if mode == "WEAK":
        noises: list[str]
        if settings.STAGE1_WEAK_NOISE_ENABLED:
            k = min(3, len(_STAGE1_WEAK_NOISE_POOL))
            noises = random.sample(_STAGE1_WEAK_NOISE_POOL, k=k)
        else:
            noises = ["관련 자료가 부족하여 추정 단서를 제시한다."]
        body = "\n\n".join(noises)
        return f"{_WEAK_HEADER.rstrip()}\n{body}"

    body = (raw_context or "").strip() or "(검색된 자료 없음)"
    return f"{_STRONG_HEADER.rstrip()}\n{body}"


def redact_stage1_answer_leak(ai_response: str, correct_answer: str) -> str:
    """AI 답변에 정답 문구가 들어가면 가려 힌트만 남긴다."""
    text = (ai_response or "").strip()
    answer = (correct_answer or "").strip()
    if not text or not answer:
        return text

    variants = _answer_match_variants(answer)
    redacted = text
    for variant in variants:
        if len(variant) < 2:
            continue
        pattern = re.compile(re.escape(variant), re.IGNORECASE)
        redacted = pattern.sub("□□□", redacted)

    # 공백 무시 매칭 (예: "동양 척식" ↔ "동양척식")
    compact_answer = _compact(answer)
    if len(compact_answer) >= 2 and _compact(redacted).find(compact_answer) >= 0:
        redacted = _replace_compact_span(redacted, compact_answer, "□□□")

    cleaned = re.sub(r"\s{2,}", " ", redacted).strip()
    if not cleaned or cleaned.replace("□", "").replace(" ", "") == "":
        return _HINT_ONLY_FALLBACK
    # 정답만 말하고 □□□로 바뀐 짧은 문장도 힌트로 교체
    if "□□□" in cleaned and len(_compact(cleaned).replace("□", "")) < 8:
        return _HINT_ONLY_FALLBACK
    if "□□□" in cleaned:
        return (
            f"{cleaned}\n\n"
            "(정답 문구는 가렸습니다. 검색된 청크의 키워드를 힌트로 스스로 답을 찾아보세요.)"
        )
    return cleaned


def _answer_match_variants(answer: str) -> list[str]:
    base = answer.strip()
    variants = [base]
    no_space = re.sub(r"\s+", "", base)
    if no_space != base:
        variants.append(no_space)
    # 흔한 조사 붙임
    for particle in ("은", "는", "이", "가", "을", "를", "과", "와", "의"):
        variants.append(base + particle)
        if no_space != base:
            variants.append(no_space + particle)
    # 긴 것부터 치환해 부분 겹침 최소화
    return sorted(set(variants), key=len, reverse=True)


def _compact(text: str) -> str:
    return re.sub(r"\s+", "", text or "").casefold()


def _replace_compact_span(text: str, compact_needle: str, replacement: str) -> str:
    """공백을 무시하고 needle과 같은 구간을 replacement로 바꾼다."""
    if not text or not compact_needle:
        return text
    needle = compact_needle.casefold()
    out: list[str] = []
    i = 0
    n = len(text)
    while i < n:
        if text[i].isspace():
            out.append(text[i])
            i += 1
            continue
        # 이 위치부터 공백 무시 매칭 시도
        j = i
        k = 0
        matched_end: int | None = None
        while j < n and k < len(needle):
            ch = text[j]
            if ch.isspace():
                j += 1
                continue
            if ch.casefold() != needle[k]:
                break
            k += 1
            j += 1
            if k == len(needle):
                matched_end = j
                break
        if matched_end is not None:
            out.append(replacement)
            i = matched_end
        else:
            out.append(text[i])
            i += 1
    return "".join(out)


_SENTENCE_BOUNDARY = frozenset(".!?。！？\n")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?。！？])\s+|\n+")
_OCR_LATIN_NOISE = re.compile(r"\b[A-Za-z]{2,}(?:\s+[A-Za-z]{2,})+\b")
_LEADING_JUNK = re.compile(r"^[\d.\s·•\-–—]+")
_LEADING_PARTICLE = re.compile(r"^[은는이가을를의와과도만께]\s+")
_TRAILING_HANG = re.compile(r"[가-힣]{1}$")  # 한 글자로 끊긴 끝
_MEANINGFUL_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")


def format_stage1_topk_sentences(
    chunks: list[str],
    document_text: str,
    *,
    max_chars: int = 220,
) -> list[str]:
    """검색 청크를 학생이 읽기 쉬운 '완결 문장'으로 정리한다.

    원문에서 겹치는 문장을 고르고 OCR 잡음을 제거한다.
    Langflow context용 원본 청크와 별개로 UI preview에만 쓴다.
    """
    sentences = _document_sentence_candidates(document_text)
    results: list[str] = []
    seen: set[str] = set()
    for chunk in chunks:
        sentence = _chunk_to_reference_sentence(
            chunk,
            document_text or "",
            sentences,
            max_chars=max_chars,
        )
        if not sentence:
            continue
        key = _compact(sentence)
        if key in seen:
            continue
        seen.add(key)
        results.append(sentence)
    return results


def _document_sentence_candidates(document_text: str) -> list[str]:
    text = (document_text or "").strip()
    if not text:
        return []
    parts = _SENTENCE_SPLIT.split(text)
    out: list[str] = []
    for part in parts:
        polished = _polish_reference_sentence(part)
        if len(_compact(polished)) < 12:
            continue
        if not _looks_readable(polished):
            continue
        out.append(polished)
    return out


def _chunk_to_reference_sentence(
    chunk: str,
    document_text: str,
    sentences: list[str],
    *,
    max_chars: int,
) -> str:
    cleaned = _polish_reference_sentence(chunk)
    if not cleaned:
        return ""

    # 1) 원문 문장 후보 중 청크와 가장 잘 맞는 완결 문장
    best = _best_matching_sentence(cleaned, sentences)
    if best:
        return _trim_reference(best, max_chars=max_chars)

    # 2) 위치 기반 확장 후 다시 문장 후보로 정제
    span = _find_chunk_span(document_text, cleaned)
    if span is not None:
        expanded = _expand_span_to_sentence(document_text, span, max_chars=max_chars * 2)
        polished = _polish_reference_sentence(expanded)
        if _looks_readable(polished) and _looks_complete(polished):
            return _trim_reference(polished, max_chars=max_chars)
        near = _best_matching_sentence(polished or cleaned, sentences)
        if near:
            return _trim_reference(near, max_chars=max_chars)
        if _looks_readable(polished):
            return _trim_reference(_ensure_sentence_end(polished), max_chars=max_chars)

    # 3) 최후: 청크 자체 정리
    if _looks_readable(cleaned):
        return _trim_reference(_ensure_sentence_end(cleaned), max_chars=max_chars)
    return ""


def _best_matching_sentence(chunk: str, sentences: list[str]) -> str | None:
    if not sentences:
        return None
    tokens = _content_tokens(chunk)
    if not tokens:
        return None

    best: str | None = None
    best_score = 0.0
    chunk_compact = _compact(chunk)
    for sentence in sentences:
        sent_compact = _compact(sentence)
        if chunk_compact and (
            chunk_compact in sent_compact or sent_compact in chunk_compact
        ):
            overlap = 1.0
            hit = len(tokens)
        else:
            sent_tokens = _content_tokens(sentence)
            if not sent_tokens:
                continue
            hit = _token_hit_count(tokens, sent_tokens, sent_compact)
            if hit == 0:
                continue
            overlap = hit / max(len(tokens), 1)
        score = overlap * 2.0 + hit * 0.08
        if _looks_complete(sentence):
            score += 0.2
        if _looks_readable(sentence):
            score += 0.1
        length = len(sentence)
        if length < 14:
            score -= 0.25
        if length > 260:
            score -= 0.08
        if score > best_score:
            best_score = score
            best = sentence

    if best is None or best_score < 0.4:
        return None
    return best


def _content_tokens(text: str) -> set[str]:
    raw = _MEANINGFUL_TOKEN.findall(text or "")
    out: set[str] = set()
    for token in raw:
        stem = _stem_token(token)
        if len(stem) >= 2:
            out.add(stem)
    return out


def _stem_token(token: str) -> str:
    t = token.casefold()
    # 조사·어미 대략 제거
    for suffix in (
        "하였다",
        "하였다",
        "합니다",
        "인가",
        "인가",
        "에서",
        "으로",
        "로서",
        "까지",
        "부터",
        "이나",
        "거나",
        "하였나",
        "하였나",
        "했다",
        "된다",
        "되는",
        "위한",
        "위한",
        "은",
        "는",
        "이",
        "가",
        "을",
        "를",
        "의",
        "와",
        "과",
        "도",
        "만",
        "에",
        "로",
    ):
        if len(t) > len(suffix) + 1 and t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return t


def _token_hit_count(
    query_tokens: set[str], sent_tokens: set[str], sent_compact: str
) -> int:
    hit = 0
    for token in query_tokens:
        if token in sent_tokens:
            hit += 1
            continue
        if len(token) >= 2 and token in sent_compact:
            hit += 1
            continue
        if any(
            st.startswith(token) or token.startswith(st)
            for st in sent_tokens
            if min(len(st), len(token)) >= 2
        ):
            hit += 1
    return hit


def _expand_span_to_sentence(
    document_text: str, span: tuple[int, int], *, max_chars: int
) -> str:
    start, end = span
    left = start
    while left > 0 and document_text[left - 1] not in _SENTENCE_BOUNDARY:
        left -= 1
        if start - left > max_chars:
            break
    right = end
    n = len(document_text)
    while right < n and document_text[right] not in _SENTENCE_BOUNDARY:
        right += 1
        if right - end > max_chars:
            break
    if right < n and document_text[right] in _SENTENCE_BOUNDARY:
        right += 1
    return document_text[left:right]


def _polish_reference_sentence(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip(" \t\n\"'“”‘’「」")
    if not s:
        return ""
    s = _OCR_LATIN_NOISE.sub(" ", s)
    s = _LEADING_JUNK.sub("", s)
    s = _LEADING_PARTICLE.sub("", s)
    # 반복 어절 축소: "약탈 탈" / "토지 약탈 탈하였나"
    s = re.sub(r"(\S{2,})\s+\1", r"\1", s)
    s = re.sub(r"([가-힣]{2,})\s+\1", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ·,;")
    # 끝 조사만 남은 미완 꼬리 제거
    s = re.sub(r"\s+[은는이가을를의와과도시]$", "", s)
    return s.strip()


def _looks_readable(text: str) -> bool:
    if not text:
        return False
    compact = _compact(text)
    if len(compact) < 10:
        return False
    hangul = len(re.findall(r"[가-힣]", text))
    if hangul < 6:
        return False
    # 라틴 잡음 비율
    latin = len(re.findall(r"[A-Za-z]", text))
    if latin > hangul:
        return False
    if re.search(r"[?]{2,}|[·]{3,}", text):
        return False
    return True


def _looks_complete(text: str) -> bool:
    s = text.strip()
    if not s:
        return False
    if s[-1] in ".!?。！？":
        return True
    # 한국어 서술·의문 어미
    if re.search(r"(다|요|까|다'|다\"|다」)$", s):
        return True
    if _TRAILING_HANG.search(s) and s[-1] not in "다요까음임함됨":
        return False
    return len(s) >= 28


def _ensure_sentence_end(text: str) -> str:
    s = text.strip()
    if not s:
        return s
    if s[-1] in ".!?。！？":
        return s
    # 미완이면 말줄임으로 표시 (가짜 종결을 붙이지 않음)
    if not _looks_complete(s):
        return f"{s.rstrip('…')}…"
    return s


def _find_chunk_span(document_text: str, chunk: str) -> tuple[int, int] | None:
    if not document_text or not chunk:
        return None
    idx = document_text.find(chunk)
    if idx >= 0:
        return idx, idx + len(chunk)

    needle = _compact(chunk)
    if len(needle) < 4:
        return None
    # 핵심 토큰만으로도 매칭 시도 (너무 긴 OCR 조각 대비)
    tokens = _MEANINGFUL_TOKEN.findall(chunk)
    if len(tokens) >= 2:
        probe = "".join(tokens[:4])
        if len(probe) >= 6:
            needle = _compact(probe)

    compact_doc: list[str] = []
    index_map: list[int] = []
    for i, ch in enumerate(document_text):
        if ch.isspace():
            continue
        compact_doc.append(ch.casefold())
        index_map.append(i)
    compact_str = "".join(compact_doc)
    pos = compact_str.find(needle.casefold())
    if pos < 0 and len(needle) > 12:
        pos = compact_str.find(needle.casefold()[:12])
    if pos < 0:
        return None
    start = index_map[pos]
    end_idx = min(pos + max(len(needle) - 1, 0), len(index_map) - 1)
    end = index_map[end_idx] + 1
    return start, end


def _trim_reference(text: str, *, max_chars: int) -> str:
    text = re.sub(r"\s+", " ", text).strip()
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars - 1].rstrip()
    if " " in cut[-24:]:
        cut = cut.rsplit(" ", 1)[0]
    return f"{cut.rstrip('…')}…"
