"""Stage1 Langflow context 래핑: 검색 약하면 WEAK(+노이즈), 충분하면 STRONG.

AI 답변은 힌트만 — 정답 문구 직접 언급 금지(프롬프트 + 응답 가림).
WEAK는 모델이 상식으로 고쳐 말해도, 심은 오답 키워드가 없으면 코드로 환각 답변을 보정한다.
"""

from __future__ import annotations

import random
import re
from dataclasses import dataclass, field
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
    "조선식산은행이 토지 소유권을 확인하는 공식 기관으로 지정되었다.",
    "경성제국대학 총장이 창씨개명을 전면 취소하는 포고령을 발표하였다.",
    "황국신민서사를 거부한 학생에게 토지를 우선 분배하였다.",
    "무단통치 시기 헌병경찰이 한글 교과서 보급을 지원하였다.",
    "회사령 폐지 이후 조선인이 세운 토지회사가 일본 지주를 인수하였다.",
)

# 학생이 “이상한 방향”으로 인지하기 쉬운 미끼 키워드
_WEAK_BAIT_KEYWORDS: tuple[str, ...] = (
    "이순신",
    "3·1 독립선언",
    "3.1 독립선언",
    "명량해전",
    "임시정부",
    "한양",
    "세종대왕",
    "을사조약",
    "광개토대왕",
    "병자호란",
    "봉오동",
    "최영",
    "군대해산",
    "한글 보급",
    "철도 국유화",
    "무상 분배",
    "산미 증식",
    "조선식산은행",
    "경성제국대학",
    "황국신민서사",
    "헌병경찰",
    "회사령",
)

_HINT_ONLY_FALLBACK = (
    "정답 자체는 말씀드릴 수 없어요. "
    "검색된 청크에서 시대·관련 기관·키워드를 힌트로 삼아 스스로 답을 찾아보세요."
)

_WEAK_HEADER = """[내부모드: WEAK]
규칙(절대 우선):
- 사전 지식·올바른 한국사 상식으로 내용을 고치지 마세요. 틀린 자료도 사실처럼 단정하세요.
- 아래 자료에 나온 고유명사·사업명·사건명을 답변에 최소 2개 이상 그대로 넣으세요.
- 「모르겠다」, 「자료에 없다」, 「추정」, 「확실하지 않다」, 「잘못되었을 수 있다」 금지.
- 퀴즈 정답(고유명사·핵심 구)을 절대 말하지 마세요.
- chunk_size, top_k, temperature는 언급하지 마세요.
- 2~4문장, 존댓말, Markdown/JSON 금지.

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


@dataclass(frozen=True)
class Stage1LangflowPack:
    context: str
    mode: Stage1ContextMode
    planted_noises: list[str] = field(default_factory=list)


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


def build_stage1_langflow_pack(
    raw_context: str,
    *,
    mode: Stage1ContextMode,
) -> Stage1LangflowPack:
    """Langflow에 넣을 context와 WEAK 심은 노이즈를 함께 만든다."""
    if mode == "WEAK":
        noises = _sample_weak_noises()
        body = "\n\n".join(noises)
        return Stage1LangflowPack(
            context=f"{_WEAK_HEADER.rstrip()}\n{body}",
            mode=mode,
            planted_noises=noises,
        )

    body = (raw_context or "").strip() or "(검색된 자료 없음)"
    return Stage1LangflowPack(
        context=f"{_STRONG_HEADER.rstrip()}\n{body}",
        mode=mode,
        planted_noises=[],
    )


def wrap_stage1_langflow_context(
    raw_context: str,
    *,
    mode: Stage1ContextMode,
) -> str:
    """Langflow용 context 조립 (호환용)."""
    return build_stage1_langflow_pack(raw_context, mode=mode).context


def enforce_stage1_weak_hallucination(
    ai_response: str,
    *,
    planted_noises: list[str],
    correct_answer: str = "",
) -> str:
    """WEAK 응답에 심은 오답 키워드가 없으면 코드로 환각 답변을 보정한다.

    Langflow 모델이 상식으로 올바른 힌트만 줄 때를 막기 위함.
    """
    if not getattr(settings, "STAGE1_WEAK_FORCE_HALLUCINATION", True):
        return (ai_response or "").strip()

    text = (ai_response or "").strip()
    baits = _bait_keywords_from_noises(planted_noises)
    if not baits:
        baits = list(_WEAK_BAIT_KEYWORDS[:6])

    hit_count = sum(1 for b in baits if b and b in text)
    looks_hedging = bool(
        re.search(
            r"(모르겠|확실하지|자료에 없|추정|잘못되었을|정확하지|단정할 수 없)",
            text,
        )
    )
    answer = (correct_answer or "").strip()
    leaks_answer = bool(answer) and (
        answer in text or _compact(answer) in _compact(text)
    )

    if hit_count >= 1 and not looks_hedging and not leaks_answer:
        return text

    return _synthesize_weak_reply(planted_noises or list(_STAGE1_WEAK_NOISE_POOL[:3]), baits)


def _sample_weak_noises() -> list[str]:
    if not settings.STAGE1_WEAK_NOISE_ENABLED:
        return ["관련 자료가 부족하여 추정 단서를 제시한다."]
    k = min(4, len(_STAGE1_WEAK_NOISE_POOL))
    return list(random.sample(_STAGE1_WEAK_NOISE_POOL, k=k))


def _bait_keywords_from_noises(noises: list[str]) -> list[str]:
    joined = "\n".join(noises)
    found = [b for b in _WEAK_BAIT_KEYWORDS if b in joined]
    # 노이즈에 있는 미끼를 우선, 없으면 전체 풀에서 일부
    return found or list(_WEAK_BAIT_KEYWORDS[:5])


def _synthesize_weak_reply(noises: list[str], baits: list[str]) -> str:
    picked = baits[:3] if baits else ["산미 증식", "한글 보급", "철도 국유화"]
    while len(picked) < 3:
        picked.append(_WEAK_BAIT_KEYWORDS[len(picked)])
    snippet = (noises[0] if noises else picked[0]).strip()
    if len(snippet) > 60:
        snippet = snippet[:57].rstrip() + "…"
    templates = (
        (
            f"자료를 보면 {picked[0]}과 관련된 내용이 먼저 나옵니다. "
            f"특히 {picked[1]} 이야기가 함께 있어서, 이 방향으로 힌트를 잡아 보시면 좋아요. "
            f"참고로 자료에는 「{snippet}」라고 적혀 있어요."
        ),
        (
            f"검색 결과에는 {picked[1]}와 {picked[2]}가 핵심 키워드로 보입니다. "
            f"{picked[0]} 맥락에서 답을 좁혀 보시면 좋을 것 같아요. "
            f"자료 문구는 「{snippet}」 정도예요."
        ),
        (
            f"이번 검색에서는 {picked[2]} 쪽이 강하게 잡혔어요. "
            f"{picked[0]}·{picked[1]}도 같이 보이니, 그 키워드들을 단서로 다시 읽어 보세요. "
            f"근거 문장은 「{snippet}」입니다."
        ),
    )
    return random.choice(templates)


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
# 교과서 OCR에서 흔한 대문자 조각 (ASS, AES, SHS 등)
_OCR_CAPS_TOKEN = re.compile(r"\b[A-Z]{2,8}\b")
_OCR_SHORT_LATIN = re.compile(r"(?<=[가-힣\s「『(\[])[A-Za-z]{2,8}(?=[가-힣\s」』)\],.、]|$)")
_LEADING_JUNK = re.compile(r"^[\d.\s·•●○▪︎‧∙\-–—\"'“”‘’「」]+")
# 조사+공백으로 시작하는 조각 문장
_LEADING_PARTICLE = re.compile(r"^[은는이가을를의와과도만께에로]\s+")
_TRAILING_HANG = re.compile(r"[가-힣]{1}$")  # 한 글자로 끊긴 끝
_MEANINGFUL_TOKEN = re.compile(r"[가-힣A-Za-z0-9]{2,}")
_KOREAN_SENTENCE_END = re.compile(
    r"(?:다|요|까|니다|습니다|였다|했다|된다)[.。!?]?$"
)
# 한국어 문장 경계 삽입용 (가변 lookbehind 회피)
_KOREAN_BREAK = re.compile(
    r"(다|요|까|니다|습니다|였다|했다|된다)(?=\s+[\"'「“]?[가-힣A-Z0-9])"
)



def format_stage1_topk_sentences(
    chunks: list[str],
    document_text: str,
    *,
    max_chars: int = 280,
) -> list[str]:
    """검색 청크를 학생이 읽기 쉬운 '완결 문장'으로 정리한다.

    원문에서 겹치는 문장을 고르고 OCR 잡음을 제거한다.
    Langflow context용 원본 청크와 별개로 UI preview에만 쓴다.
    미완·말줄임 조각은 학생에게 보여 주지 않는다.
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
        if not sentence or not _is_student_ready(sentence):
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
    marked = _KOREAN_BREAK.sub(r"\1\n", text)
    parts = _SENTENCE_SPLIT.split(marked)
    out: list[str] = []
    for part in parts:
        polished = _polish_reference_sentence(part)
        if len(_compact(polished)) < 12:
            continue
        if not _looks_readable(polished):
            continue
        if not _looks_complete(polished):
            continue
        if _starts_like_fragment(polished):
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
    if best and _is_student_ready(best):
        return _trim_reference(best, max_chars=max_chars)

    # 2) 위치 기반 확장 후 다시 문장 후보로 정제
    span = _find_chunk_span(document_text, cleaned) or _find_chunk_span(
        document_text, chunk
    )
    if span is not None:
        expanded = _expand_span_to_sentence(
            document_text, span, max_chars=max(max_chars * 2, 360)
        )
        polished = _polish_reference_sentence(expanded)
        if _is_student_ready(polished):
            return _trim_reference(polished, max_chars=max_chars)
        near = _best_matching_sentence(polished or cleaned, sentences)
        if near and _is_student_ready(near):
            return _trim_reference(near, max_chars=max_chars)
        # 확장문이 길면 내부에서 완결 문장만 추출
        for part in _SENTENCE_SPLIT.split(_KOREAN_BREAK.sub(r"\1\n", expanded)):
            cand = _polish_reference_sentence(part)
            if _is_student_ready(cand) and _shares_content(cleaned, cand):
                return _trim_reference(cand, max_chars=max_chars)

    # 3) 최후: 청크 자체가 완결 문장일 때만 (말줄임 조각은 버림)
    if _is_student_ready(cleaned):
        return _trim_reference(cleaned, max_chars=max_chars)
    return ""


def _shares_content(chunk: str, sentence: str) -> bool:
    tokens = _content_tokens(chunk)
    if not tokens:
        return False
    sent_tokens = _content_tokens(sentence)
    if not sent_tokens:
        return False
    hit = _token_hit_count(tokens, sent_tokens, _compact(sentence))
    return hit / max(len(tokens), 1) >= 0.35


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
            score += 0.35
        if _looks_readable(sentence):
            score += 0.1
        if _starts_like_fragment(sentence):
            score -= 0.8
        length = len(sentence)
        if length < 14:
            score -= 0.25
        if length > 260:
            score -= 0.08
        if score > best_score:
            best_score = score
            best = sentence

    if best is None or best_score < 0.45:
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
        "합니다",
        "인가",
        "에서",
        "으로",
        "로서",
        "까지",
        "부터",
        "이나",
        "거나",
        "하였나",
        "했다",
        "된다",
        "되는",
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
    while left > 0:
        prev = document_text[left - 1]
        if prev in _SENTENCE_BOUNDARY:
            break
        # 직전 문장이 한국어 종결어미로 끝났으면 거기서 멈춤
        window = document_text[max(0, left - 8) : left]
        if _KOREAN_SENTENCE_END.search(window.rstrip()):
            break
        left -= 1
        if start - left > max_chars:
            break
    right = end
    n = len(document_text)
    while right < n:
        ch = document_text[right]
        if ch in _SENTENCE_BOUNDARY:
            right += 1
            break
        right += 1
        window = document_text[max(start, right - 8) : right]
        if _KOREAN_SENTENCE_END.search(window.rstrip()) and (
            right >= n or document_text[right].isspace() or document_text[right] in "\"'”’」"
        ):
            break
        if right - end > max_chars:
            break
    return document_text[left:right]


def _polish_reference_sentence(text: str) -> str:
    s = re.sub(r"\s+", " ", (text or "")).strip(" \t\n\"'“”‘’「」")
    if not s:
        return ""
    s = _OCR_LATIN_NOISE.sub(" ", s)
    s = _OCR_CAPS_TOKEN.sub(" ", s)
    s = _OCR_SHORT_LATIN.sub(" ", s)
    s = _LEADING_JUNK.sub("", s)
    s = _LEADING_PARTICLE.sub("", s)
    # 반복 어절 축소: "약탈 탈" / "토지 약탈 탈하였나"
    s = re.sub(r"(\S{2,})\s+\1", r"\1", s)
    s = re.sub(r"([가-힣]{2,})\s+\1", r"\1", s)
    s = re.sub(r"\s{2,}", " ", s).strip(" ·,;•●")
    # 끝 조사만 남은 미완 꼬리 제거
    s = re.sub(r"\s+[은는이가을를의와과도시]$", "", s)
    return s.strip()


def _starts_like_fragment(text: str) -> bool:
    s = (text or "").strip()
    if not s:
        return True
    if s[0] in "·•●○▪︎‧∙-–—":
        return True
    if _LEADING_PARTICLE.match(s):
        return True
    # 조사·접속만으로 시작
    if re.match(r"^(그리고|그러나|하지만|또는|및)\s*$", s):
        return True
    return False


def _is_student_ready(text: str) -> bool:
    """학생 UI에 보여줄 만큼 읽히는 완결 문장인지."""
    s = (text or "").strip()
    if not s:
        return False
    if s.endswith("…") or s.endswith("..."):
        return False
    if _starts_like_fragment(s):
        return False
    if not _looks_readable(s):
        return False
    if not _looks_complete(s):
        return False
    # OCR 대문자/짧은 라틴 조각이 남아 있으면 제외 (한글이 많아도)
    if _OCR_CAPS_TOKEN.search(s) or _OCR_SHORT_LATIN.search(s):
        return False
    if _OCR_LATIN_NOISE.search(s):
        return False
    # "등의 ASS 통해" → 정리 후 "등의 통해"처럼 명사가 비는 경우
    if re.search(r"등의\s*통해", s):
        return False
    return True


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
    if latin > max(2, hangul // 8):
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
    if _KOREAN_SENTENCE_END.search(s):
        return True
    # 한국어 서술·의문 어미
    if re.search(r"(다|요|까)$", s):
        return True
    if _TRAILING_HANG.search(s) and s[-1] not in "다요까음임함됨":
        return False
    return False


def _ensure_sentence_end(text: str) -> str:
    s = text.strip()
    if not s:
        return s
    if s[-1] in ".!?。！？":
        return s
    if _looks_complete(s):
        return s
    # 미완 조각에 가짜 종결·말줄임을 붙이지 않음 (학생 UI에서 버림)
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

    window = text[:max_chars]
    best = ""
    for match in _KOREAN_SENTENCE_END.finditer(window):
        candidate = window[: match.end()].strip()
        if _is_student_ready(candidate) and len(candidate) > len(best):
            best = candidate
    for sep in (". ", "! ", "? ", "。"):
        idx = window.rfind(sep)
        if idx >= 20:
            candidate = window[: idx + 1].strip()
            if _is_student_ready(candidate) and len(candidate) > len(best):
                best = candidate
    if best:
        return best
    # 말줄임으로 자르지 않음 — 완결 문장만 허용
    if _is_student_ready(text):
        return text
    return ""

