"""토론 근거에 대한 실제 뉴스·인터뷰 검색."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

from app.services.stage3_debate import NEEDS_CHECK

logger = logging.getLogger(__name__)


def _norm_text(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().lower())


_MOCK_TITLE_SUFFIX = re.compile(r"\s*—\s*.+$")


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


async def google_news(query: str, kind: str = "뉴스", limit: int = 6) -> list[dict]:
    url = (
        "https://news.google.com/rss/search"
        f"?q={quote(query)}&hl=ko&gl=KR&ceid=KR:ko"
    )
    async with httpx.AsyncClient(timeout=12.0, follow_redirects=True) as client:
        response = await client.get(
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; EduFlow/1.0)",
                "Accept": "application/rss+xml, application/xml, text/xml, */*",
            },
        )
        response.raise_for_status()
        return _parse_rss(response.content, kind)[:limit]


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
        queries.append((claim[:120], "기사"))
        if topic:
            queries.append((f"{claim[:72]} {topic[:36]}", "뉴스"))
    elif len(text) >= 10:
        queries.append((text[:120], "기사"))

    seen: set[str] = set()
    articles: list[dict] = []
    for query, kind in queries:
        try:
            batch = _dedupe_articles(await google_news(query, kind=kind, limit=3), seen)
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
    if is_mock:
        return mock_turn_sources(topic, claim_text)
    found = await fetch_turn_sources(topic, claim_text, limit=3)
    return found or mock_turn_sources(topic, claim_text)


def _merge_source_items(*groups: list[dict], limit: int = 8) -> list[dict]:
    seen: set[str] = set()
    merged: list[dict] = []
    for group in groups:
        for item in _dedupe_articles(group, seen):
            merged.append(item)
            if len(merged) >= limit:
                return merged
    return merged


async def attach_turn_sources(payload: dict, topic: str) -> None:
    """토론 payload 각 turn·claim에 생성 시점 출처를 저장한다."""

    turns = payload.get("turns") or []
    if not turns:
        return
    is_mock = str(payload.get("source") or "") == "mock"
    for turn in turns:
        claim_groups: list[list[dict]] = []

        for item in turn.get("claims") or []:
            if not isinstance(item, dict):
                continue
            claim_text = str(item.get("claim") or "").strip()
            if len(claim_text) < 8:
                continue
            per_claim = await _sources_for_claim_text(topic, claim_text, is_mock=is_mock)
            item["sources"] = per_claim
            claim_groups.append(per_claim)

        for claim_text in _collect_turn_claim_texts(turn):
            if any(_norm_text(claim_text) == _norm_text(str(c.get("claim") or "")) for c in turn.get("claims") or [] if isinstance(c, dict)):
                continue
            claim_groups.append(await _sources_for_claim_text(topic, claim_text, is_mock=is_mock))

        turn["sources"] = _merge_source_items(*claim_groups, limit=8)
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
                    return _merge_source_items(stored)

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

    return _merge_source_items(*groups, limit=8)


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
                        return _merge_source_items(stored)
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
