"""토론 근거에 대한 실제 뉴스·인터뷰 검색."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, quote, unquote, urlparse

import time

import httpx

from app.services.stage3_debate import NEEDS_CHECK, overlap_ratio

logger = logging.getLogger(__name__)

_google_news_blocked_until: float = 0.0

_ARTICLE_REF = re.compile(r"[\[(]?기사\s*(\d+)[\])]?")


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_MOCK_TITLE_SUFFIX = re.compile(r"\s*—\s*.+$")
_PLACEHOLDER_URL = re.compile(
    r"news\.google\.com/search\?|search\.naver\.com/search\.naver|bing\.com/news/apiclick",
    re.I,
)


def is_real_article(item: dict) -> bool:
    """검색 페이지·(예시) placeholder는 실제 기사로 취급하지 않는다."""
    title = (item.get("title") or "").strip()
    url = (item.get("url") or "").strip()
    if len(title) < 4 or not url:
        return False
    if "(예시)" in title:
        return False
    if _PLACEHOLDER_URL.search(url):
        return False
    return True


def filter_real_articles(items: list[dict]) -> list[dict]:
    return [item for item in items if is_real_article(item)]


def _article_dedupe_key(item: dict) -> str:
    """제목 핵심(접미사 제외) 또는 URL로 중복 판별."""
    title = (item.get("title") or "").strip()
    core = _MOCK_TITLE_SUFFIX.sub("", title)
    core_key = re.sub(r"\s+", "", core.lower())
    if core_key:
        return f"t:{core_key}"
    url = (item.get("url") or "").strip().lower()
    if url:
        return f"u:{url}"
    return ""


def _dedupe_articles(items: list[dict], seen: set[str] | None = None) -> list[dict]:
    out: list[dict] = []
    if seen is None:
        seen = set()
    for item in items:
        key = _article_dedupe_key(item)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(item)
    return out


def _parse_rss(raw: bytes, kind: str) -> list[dict]:
    items: list[dict] = []
    try:
        root = ET.fromstring(raw)
    except ET.ParseError:
        return items
    for item in root.findall(".//item"):
        title = html.unescape((item.findtext("title") or "").strip())
        link = (item.findtext("link") or "").strip()
        pub = (item.findtext("pubDate") or "").strip()
        source_el = item.find("source")
        source = (source_el.text or "").strip() if source_el is not None else ""
        desc = html.unescape(item.findtext("description") or "")
        href = re.search(r'href="([^"]+)"', desc)
        if href and "news.google.com" in link:
            link = html.unescape(href.group(1))
        if "news.google.com/rss/articles/" in link:
            link = link.replace("/rss/articles/", "/articles/")
        link = _unwrap_news_url(link)
        if not source:
            for child in list(item):
                tag = (child.tag or "").lower()
                if tag.endswith("source") and (child.text or "").strip():
                    source = child.text.strip()
                    break
        if " - " in title and not source:
            title, source = title.rsplit(" - ", 1)
        if not title or not link:
            continue
        items.append(
            {
                "title": title,
                "url": link,
                "source": source or "뉴스",
                "published": pub,
                "kind": kind,
            }
        )
    return items


def _unwrap_news_url(link: str) -> str:
    """Bing/Google 리다이렉트 URL이면 실제 기사 URL을 꺼낸다."""
    link = (link or "").strip()
    if not link:
        return link
    host = urlparse(link).netloc.lower()
    if "bing.com" in host and "apiclick" in link:
        inner = (parse_qs(urlparse(link).query).get("url") or [""])[0]
        if inner:
            return unquote(inner)
    return link


_HTTP_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; EduFlow/1.0)",
    "Accept": "application/rss+xml, application/xml, text/xml, */*",
}


def _shorten_query(query: str, max_chars: int = 60) -> str:
    """긴 문장을 Google News RSS에 적합한 짧은 키워드로 축약한다."""
    query = re.sub(r"\(출처[^)]*\)", "", query).strip()
    query = re.sub(r"\[기사\d+\]", "", query).strip()
    query = re.sub(r"['\"""''`]", "", query)
    query = re.sub(r"\s+", " ", query).strip()
    if len(query) <= max_chars:
        return query
    words = query.split()
    result: list[str] = []
    length = 0
    for w in words:
        if length + len(w) + 1 > max_chars:
            break
        result.append(w)
        length += len(w) + 1
    return " ".join(result) if result else query[:max_chars]


async def google_news(query: str, kind: str = "뉴스", limit: int = 6) -> list[dict]:
    global _google_news_blocked_until
    if time.monotonic() < _google_news_blocked_until:
        return []
    query = _shorten_query(query)
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    )
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        response = await client.get(url, headers=_HTTP_HEADERS)
        if response.status_code == 503:
            _google_news_blocked_until = time.monotonic() + 300
            logger.warning("Google News 503 — 5분간 검색 중단")
            return []
        response.raise_for_status()
        return _parse_rss(response.content, kind)[:limit]


async def bing_news(query: str, kind: str = "뉴스", limit: int = 6) -> list[dict]:
    query = _shorten_query(query)
    url = f"https://www.bing.com/news/search?q={quote(query)}&format=rss"
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        response = await client.get(url, headers=_HTTP_HEADERS)
        response.raise_for_status()
        return filter_real_articles(_parse_rss(response.content, kind))[:limit]


async def search_news(query: str, kind: str = "뉴스", limit: int = 6) -> list[dict]:
    """Google News를 우선 쓰고, 막히면 Bing News로 실제 기사를 가져온다."""
    try:
        articles = filter_real_articles(await google_news(query, kind=kind, limit=limit))
        if articles:
            return articles
    except httpx.HTTPError as exc:
        logger.warning("Google News failed for %s: %s", query, exc)
    try:
        articles = await bing_news(query, kind=kind, limit=limit)
        if articles:
            logger.info("Bing News fallback used for %s (%s articles)", query, len(articles))
        return articles
    except httpx.HTTPError as exc:
        logger.warning("Bing News failed for %s: %s", query, exc)
        return []


def _law_extras(blob: str) -> list[dict]:
    extras: list[dict] = []
    if "개인정보보호법" in blob or "민감정보" in blob:
        extras.append(
            {
                "title": "개인정보 보호법",
                "url": "https://www.law.go.kr/법령/개인정보보호법",
                "source": "국가법령정보센터",
                "published": "",
                "kind": "법령",
            }
        )
    return extras


async def fetch_topic_articles(topic: str, *, limit: int = 12) -> list[dict]:
    """토론 생성 전 주제 관련 실제 뉴스를 수집한다."""

    topic = (topic or "").strip()
    if not topic:
        return []

    queries = [
        (topic[:80], "뉴스"),
        (f"{topic[:48]} 논란", "기사"),
        (f"{topic[:48]} 교육", "기사"),
    ]
    seen: set[str] = set()
    articles: list[dict] = []
    for query, kind in queries:
        try:
            batch = await search_news(query, kind=kind, limit=5)
            articles.extend(_dedupe_articles(batch, seen))
        except httpx.HTTPError as exc:
            logger.warning("stage3 topic news fetch failed for %s: %s", query, exc)
        if len(articles) >= limit:
            break
    return articles[:limit]


def format_news_brief(articles: list[dict]) -> str:
    lines: list[str] = []
    for index, item in enumerate(articles, start=1):
        title = (item.get("title") or "").strip()
        if not title:
            continue
        source = (item.get("source") or "").strip()
        published = (item.get("published") or "").strip()
        meta = f" ({source})" if source else ""
        if published:
            meta += f" · {published[:20]}"
        lines.append(f"기사{index}. {title}{meta}")
    return "\n".join(lines)


def parse_article_refs(text: str) -> list[int]:
    return [int(value) for value in _ARTICLE_REF.findall(text or "")]


def _article_at(pool: list[dict], index: int) -> dict | None:
    if 1 <= index <= len(pool):
        return pool[index - 1]
    return None


def sources_for_claim_text(
    claim_text: str,
    pool: list[dict],
    *,
    used_indices: set[int] | None = None,
) -> list[dict]:
    """근거 문장의 [기사N] 표기 또는 제목 유사도로 기사를 연결한다."""

    claim_text = (claim_text or "").strip()
    if not claim_text or not pool:
        return []

    matched: list[dict] = []
    seen_keys: set[str] = set()
    for ref in parse_article_refs(claim_text):
        article = _article_at(pool, ref)
        if not article:
            continue
        key = _article_dedupe_key(article)
        if key and key not in seen_keys:
            seen_keys.add(key)
            matched.append(article)
            if used_indices is not None:
                used_indices.add(ref - 1)

    matched = filter_real_articles(_dedupe_articles(matched))
    if matched:
        return matched

    best_index: int | None = None
    best_score = 0.12
    for index, article in enumerate(pool):
        if used_indices is not None and index in used_indices:
            continue
        blob = f"{article.get('title') or ''} {article.get('source') or ''}"
        score = overlap_ratio(claim_text, blob)
        if score > best_score:
            best_score = score
            best_index = index

    if best_index is None:
        return []

    if used_indices is not None:
        used_indices.add(best_index)
    return filter_real_articles([pool[best_index]])


def link_claims_to_topic_articles(
    payload: dict,
    topic_articles: list[dict] | None = None,
    *,
    force: bool = False,
) -> None:
    """토론 생성에 쓴 topic_articles pool을 각 근거·출처에 연결한다."""

    pool = filter_real_articles(topic_articles or payload.get("topic_articles") or [])
    if not pool:
        return

    payload["topic_articles"] = pool
    for turn in payload.get("turns") or []:
        if not isinstance(turn, dict):
            continue
        if not force and turn_has_stored_sources(turn):
            continue

        used: set[int] = set()
        claim_groups: list[list[dict]] = []

        for item in turn.get("claims") or []:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim") or "").strip()
            if len(claim_text) < 8:
                continue
            existing = filter_real_articles(item.get("sources") or [])
            if not force and existing:
                claim_groups.append(existing)
                continue
            linked = sources_for_claim_text(claim_text, pool, used_indices=used)
            item["sources"] = linked
            if linked:
                claim_groups.append(linked)

        for ground in turn.get("grounds") or []:
            ground_text = str(ground).strip()
            if len(ground_text) < 8:
                continue
            if any(
                _norm_text(ground_text) == _norm_text(str(c.get("claim") or ""))
                for c in turn.get("claims") or []
                if isinstance(c, dict)
            ):
                continue
            linked = sources_for_claim_text(ground_text, pool, used_indices=used)
            if linked:
                claim_groups.append(linked)

        turn["sources"] = filter_real_articles(_merge_source_items(*claim_groups, limit=8))
        if not turn["sources"]:
            fallback = str(turn.get("claim") or turn.get("text") or "").strip()
            if fallback:
                turn["sources"] = sources_for_claim_text(fallback, pool)


async def fetch_turn_sources(
    topic: str,
    claim: str = "",
    text: str = "",
    *,
    limit: int = 4,
) -> list[dict]:
    """한 발언(근거)에 맞춘 좁은 뉴스 검색 — 토론 생성 시 미리 붙일 출처."""

    claim = (claim or "").strip()
    text = (text or "").strip()
    topic = (topic or "").strip()
    queries: list[tuple[str, str]] = []
    if len(claim) >= 8:
        queries.append((claim[:60], "기사"))
        if topic:
            queries.append((f"{topic[:30]} {claim[:30]}", "뉴스"))
    elif len(text) >= 10:
        queries.append((text[:60], "기사"))

    seen: set[str] = set()
    articles: list[dict] = []
    for query, kind in queries:
        try:
            batch = _dedupe_articles(await search_news(query, kind=kind, limit=3), seen)
            articles.extend(batch)
        except httpx.HTTPError as exc:
            logger.warning("stage3 turn source search failed for %s: %s", query, exc)
        if len(articles) >= limit:
            break

    blob = " ".join(part for part in (topic, claim, text) if part)
    extras = _law_extras(blob)
    articles = _dedupe_articles(extras + articles, seen)
    return articles[:limit]


def mock_turn_sources(topic: str, claim: str, text: str = "") -> list[dict]:
    label = (claim or text or topic or "토론 근거").strip()[:72]
    q = quote(label)
    return [
        {
            "title": f"{label} — 관련 보도 (예시)",
            "url": f"https://news.google.com/search?q={q}&hl=ko&gl=KR&ceid=KR:ko",
            "source": "Google 뉴스",
            "published": "",
            "kind": "기사",
        },
    ]


def _collect_turn_claim_texts(turn: dict) -> list[str]:
    """팩트체크 flagged 근거(과장·허위 등)를 우선 수집한다."""

    flawed: list[str] = []
    other: list[str] = []
    seen: set[str] = set()

    def add(text: str, *, flawed_first: bool = False) -> None:
        cleaned = (text or "").strip()
        if len(cleaned) < 8:
            return
        key = _norm_text(cleaned)
        if key in seen:
            return
        seen.add(key)
        (flawed if flawed_first else other).append(cleaned)

    for item in turn.get("claims") or []:
        if not isinstance(item, dict):
            continue
        verdict = str(item.get("verdict") or "")
        add(str(item.get("claim") or ""), flawed_first=verdict in NEEDS_CHECK)

    add(str(turn.get("claim") or ""))
    for ground in turn.get("grounds") or []:
        add(str(ground))

    for item in turn.get("claims") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("verdict") or "") in NEEDS_CHECK:
            continue
        add(str(item.get("claim") or ""))

    return flawed + other


async def _sources_for_claim_text(topic: str, claim_text: str, *, is_mock: bool) -> list[dict]:
    del is_mock  # 토론 mock 여부와 무관하게 실제 RSS 기사만 저장
    found = await fetch_turn_sources(topic, claim_text, limit=3)
    return filter_real_articles(found)


def _merge_source_items(*groups: list[dict], limit: int = 8) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for group in groups:
        for item in _dedupe_articles(group, seen):
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


def turn_has_stored_sources(turn: dict) -> bool:
    return bool(filter_real_articles(_sources_for_turn(turn)))


def debate_has_stored_sources(payload: dict | None) -> bool:
    if not payload:
        return False
    for turn in payload.get("turns") or []:
        if isinstance(turn, dict) and turn_has_stored_sources(turn):
            return True
    return False


async def attach_turn_sources(payload: dict, topic: str, *, force: bool = False) -> None:
    """토론 payload 각 turn·claim에 생성 시점 출처를 저장한다."""

    pool = filter_real_articles(payload.get("topic_articles") or [])
    if pool:
        link_claims_to_topic_articles(payload, pool, force=force)
        return

    turns = payload.get("turns") or []
    if not turns:
        return
    is_mock = str(payload.get("source") or "") == "mock"
    for turn in turns:
        if not force and turn_has_stored_sources(turn):
            continue

        claim_groups: list[list[dict]] = []

        for item in turn.get("claims") or []:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim") or "").strip()
            if len(claim_text) < 8:
                continue
            existing = item.get("sources") or []
            if not force and filter_real_articles(existing if isinstance(existing, list) else []):
                claim_groups.append(filter_real_articles(existing))
                continue
            per_claim = await _sources_for_claim_text(topic, claim_text, is_mock=is_mock)
            item["sources"] = per_claim
            claim_groups.append(per_claim)

        for claim_text in _collect_turn_claim_texts(turn):
            if any(_norm_text(claim_text) == _norm_text(str(c.get("claim") or "")) for c in turn.get("claims") or [] if isinstance(c, dict)):
                continue
            claim_groups.append(await _sources_for_claim_text(topic, claim_text, is_mock=is_mock))

        turn["sources"] = _merge_source_items(*claim_groups, limit=8)
        turn["sources"] = filter_real_articles(turn["sources"])
        if not turn["sources"]:
            fallback = str(turn.get("claim") or turn.get("text") or topic)
            turn["sources"] = await _sources_for_claim_text(topic, fallback, is_mock=is_mock)


def _sources_for_turn(turn: dict, *, claim: str = "") -> list[dict]:
    if claim:
        normalized = _norm_text(claim)
        for item in turn.get("claims") or []:
            if not isinstance(item, dict):
                continue
            if _norm_text(str(item.get("claim") or "")) == normalized:
                stored = item.get("sources") or []
                if isinstance(stored, list) and stored:
                    return filter_real_articles(_merge_source_items(stored))

    groups: list[list[dict]] = []
    stored_turn = turn.get("sources") or []
    if isinstance(stored_turn, list) and stored_turn:
        groups.append(stored_turn)

    for item in turn.get("claims") or []:
        if not isinstance(item, dict):
            continue
        stored = item.get("sources") or []
        if isinstance(stored, list) and stored:
            groups.append(stored)

    return filter_real_articles(_merge_source_items(*groups, limit=8))


def find_turn_sources(
    debate_payload: dict | None,
    *,
    turn_id: str | None = None,
    claim: str = "",
) -> list[dict]:
    if not debate_payload:
        return []
    turns = debate_payload.get("turns") or []
    if turn_id:
        turn = next((item for item in turns if str(item.get("id")) == turn_id), None)
        if turn:
            return _sources_for_turn(turn, claim=claim)
    if claim:
        normalized = _norm_text(claim)
        for turn in turns:
            for item in turn.get("claims") or []:
                if not isinstance(item, dict):
                    continue
                if _norm_text(str(item.get("claim") or "")) == normalized:
                    stored = item.get("sources") or []
                    if isinstance(stored, list) and stored:
                        return filter_real_articles(_merge_source_items(stored))
            for candidate in [str(turn.get("claim") or ""), *(turn.get("grounds") or [])]:
                if _norm_text(candidate) == normalized:
                    return _sources_for_turn(turn, claim=candidate)
    return []


async def search_sources(topic: str, claim: str = "", text: str = "") -> dict:
    """레거시 폴백 — 넓은 검색 대신 발언 단위 좁은 검색을 사용한다."""

    articles = await fetch_turn_sources(topic, claim, text, limit=6)
    return {
        "query": claim or topic,
        "articles": articles,
        "searches": [],
        "errors": [],
    }
