import pytest

from app.services.stage3_sources import (
    _dedupe_articles,
    debate_has_stored_sources,
    filter_real_articles,
    find_turn_sources,
    format_news_brief,
    is_real_article,
    link_claims_to_topic_articles,
    mock_turn_sources,
    parse_article_refs,
    sources_for_claim_text,
    turn_has_stored_sources,
)


def test_find_turn_sources_by_turn_id() -> None:
    payload = {
        "turns": [
            {
                "id": "pro-1",
                "claim": "AI세는 재분배 재원이 될 수 있다.",
                "sources": [
                    {
                        "title": "AI세 도입 논의",
                        "url": "https://example.com/a",
                        "source": "조선일보",
                        "published": "",
                        "kind": "기사",
                    }
                ],
            }
        ]
    }
    found = find_turn_sources(payload, turn_id="pro-1")
    assert len(found) == 1
    assert found[0]["title"] == "AI세 도입 논의"


def test_find_turn_sources_empty_without_match() -> None:
    assert find_turn_sources({"turns": []}, turn_id="pro-1") == []


def test_find_turn_sources_includes_flawed_claim_sources() -> None:
    payload = {
        "turns": [
            {
                "id": "con-1",
                "claim": "AI세는 필요하다.",
                "sources": [{"title": "대표 근거 기사", "url": "https://example.com/main", "source": "A", "published": "", "kind": "기사"}],
                "claims": [
                    {
                        "claim": "전국 80% 학교가 이미 AI 감독을 도입했다.",
                        "verdict": "false",
                        "reason": "과장된 수치",
                        "sources": [
                            {
                                "title": "AI 감독 도입 현황 보도",
                                "url": "https://example.com/flaw",
                                "source": "B",
                                "published": "",
                                "kind": "기사",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    found = find_turn_sources(payload, turn_id="con-1")
    titles = {item["title"] for item in found}
    assert "대표 근거 기사" in titles
    assert "AI 감독 도입 현황 보도" in titles


def test_find_turn_sources_by_flawed_claim_text() -> None:
    payload = {
        "turns": [
            {
                "id": "con-1",
                "claims": [
                    {
                        "claim": "로봇세는 일자리를 보호한다.",
                        "verdict": "exaggerated",
                        "sources": [
                            {
                                "title": "로봇세 관련 기사",
                                "url": "https://example.com/tax",
                                "source": "C",
                                "published": "",
                                "kind": "기사",
                            }
                        ],
                    }
                ],
            }
        ]
    }
    found = find_turn_sources(payload, claim="로봇세는 일자리를 보호한다.")
    assert len(found) == 1
    assert found[0]["title"] == "로봇세 관련 기사"


def test_mock_turn_sources_returns_single_item() -> None:
    assert len(mock_turn_sources("AI 교육", "자율주행차 사고율 90% 감소")) == 1


def test_dedupe_strips_mock_title_suffix() -> None:
    items = [
        {
            "title": "연구에 따르면, 자율주행차가 도입되면 — 관련 정책·산업 보도 (예시)",
            "url": "https://news.google.com/search?q=a",
        },
        {
            "title": "연구에 따르면, 자율주행차가 도입되면 — 전문가 인터뷰·해설 (예시)",
            "url": "https://search.naver.com/search.naver?query=a",
        },
    ]
    assert len(_dedupe_articles(items)) == 1


def test_debate_has_stored_sources() -> None:
    assert not debate_has_stored_sources({"turns": [{"id": "a", "claim": "x"}]})
    assert debate_has_stored_sources(
        {
            "turns": [
                {
                    "id": "a",
                    "sources": [{"title": "기사", "url": "https://example.com", "source": "A", "published": "", "kind": "기사"}],
                }
            ]
        }
    )


def test_turn_has_stored_sources_from_claim() -> None:
    turn = {
        "claims": [
            {
                "claim": "로봇세는 일자리를 보호한다.",
                "sources": [{"title": "기사", "url": "https://example.com", "source": "A", "published": "", "kind": "기사"}],
            }
        ]
    }
    assert turn_has_stored_sources(turn)


def test_filter_real_articles_rejects_placeholder() -> None:
    mock = mock_turn_sources("AI 교육", "자율주행차 사고율 90% 감소")
    assert not is_real_article(mock[0])
    assert filter_real_articles(mock) == []
    assert filter_real_articles(
        [{"title": "AI세 도입", "url": "https://news.google.com/rss/articles/abc", "source": "조선", "published": "", "kind": "기사"}]
    )


def test_format_news_brief_and_article_refs() -> None:
    articles = [
        {"title": "AI 교육 도입", "url": "https://example.com/a", "source": "연합", "published": "", "kind": "기사"},
        {"title": "개인정보 우려", "url": "https://example.com/b", "source": "조선", "published": "", "kind": "기사"},
    ]
    brief = format_news_brief(articles)
    assert "기사1. AI 교육 도입" in brief
    assert parse_article_refs("보도에 따르면 효과가 있다. [기사1]") == [1]


def test_link_claims_to_topic_articles_by_ref() -> None:
    pool = [
        {"title": "AI 교육 도입 확대", "url": "https://example.com/a", "source": "연합", "published": "", "kind": "기사"},
        {"title": "개인정보 보호 논란", "url": "https://example.com/b", "source": "조선", "published": "", "kind": "기사"},
    ]
    payload = {
        "topic_articles": pool,
        "turns": [
            {
                "id": "pro-1",
                "claim": "AI 교육 도입 확대",
                "grounds": ["AI 교육 도입 확대 보도가 있다. [기사1]"],
                "claims": [],
            }
        ],
    }
    link_claims_to_topic_articles(payload, pool)
    found = find_turn_sources(payload, turn_id="pro-1")
    assert len(found) == 1
    assert found[0]["title"] == "AI 교육 도입 확대"


def test_sources_for_claim_text_overlap() -> None:
    pool = [
        {"title": "로봇세 도입 논의", "url": "https://example.com/tax", "source": "한경", "published": "", "kind": "기사"},
    ]
    linked = sources_for_claim_text("로봇세 도입이 일자리 보호에 도움이 된다.", pool)
    assert len(linked) == 1
    assert linked[0]["title"] == "로봇세 도입 논의"
