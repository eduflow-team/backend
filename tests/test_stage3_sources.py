import pytest

from app.services.stage3_sources import _dedupe_articles, find_turn_sources, mock_turn_sources


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
