"""토론 근거에 대한 실제 뉴스·인터뷰 검색."""

from __future__ import annotations

import html
import logging
import re
import xml.etree.ElementTree as ET
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

_STOP = {
    "그리고",
    "하지만",
    "그러나",
    "것으로",
    "있습니다",
    "합니다",
    "입니다",
    "있다",
    "없다",
    "위해",
    "대한",
    "통해",
    "관련",
    "문제",
    "때문에",
    "아니다",
}


def _keywords(*parts: str) -> list[str]:
    blob = " ".join(p for p in parts if p)
    words = re.findall(r"[가-힣]{2,}|[A-Za-z]{3,}", blob)
    seen: list[str] = []
    for word in words:
        if word in _STOP or word in seen:
            continue
        seen.append(word)
        if len(seen) >= 8:
            break
    return seen


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


async def search_sources(topic: str, claim: str = "", text: str = "") -> dict:
    queries: list[tuple[str, str]] = []
    if topic:
        queries.append((topic, "뉴스"))
        queries.append((f"{topic} 인터뷰", "인터뷰"))
        queries.append((f"{topic} 기사", "기사"))
    keys = _keywords(claim, text)
    if keys:
        queries.append((" ".join(keys[:5]), "뉴스"))
    if claim and len(claim) >= 8:
        queries.append((claim[:80], "기사"))

    seen: set[str] = set()
    articles: list[dict] = []
    errors: list[str] = []
    for query, kind in queries:
        try:
            for item in await google_news(query, kind=kind, limit=5):
                key = re.sub(r"\s+", "", item["title"]).lower()
                if key in seen:
                    continue
                seen.add(key)
                articles.append(item)
                if len(articles) >= 8:
                    break
        except httpx.HTTPError as exc:
            logger.warning("stage3 news search failed for %s: %s", query, exc)
            errors.append(str(exc))
        if len(articles) >= 8:
            break

    blob = f"{topic} {claim} {text}"
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

    q = quote((topic or claim or "교육 AI")[:80])
    searches = [
        {
            "title": f"'{topic or claim}' Google 뉴스",
            "url": f"https://news.google.com/search?q={q}&hl=ko&gl=KR&ceid=KR:ko",
            "source": "Google 뉴스",
            "published": "",
            "kind": "검색",
        },
        {
            "title": f"'{topic or claim}' 네이버 뉴스",
            "url": f"https://search.naver.com/search.naver?where=news&query={q}",
            "source": "네이버 뉴스",
            "published": "",
            "kind": "검색",
        },
    ]
    return {
        "query": topic,
        "articles": extras + articles,
        "searches": searches,
        "errors": errors[:3],
    }
