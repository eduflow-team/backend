from app.services.stage3_demo import DEMO_ARTICLES, build_demo_payload, is_demo_topic
from app.services.stage3_sources import debate_has_stored_sources, find_turn_sources


def test_is_demo_topic_matches_spaced_and_compact() -> None:
    assert is_demo_topic("중고등학생의 AI 활용 과제 제출을 허용해야 하는가")
    assert is_demo_topic("중고등학생의AI활용과제제출을허용해야하는가")
    assert not is_demo_topic("초등학교 AI 학습 도구 의무 도입")


def test_demo_payload_has_turns_and_real_sources() -> None:
    payload = build_demo_payload(
        topic="중고등학생의 AI 활용 과제 제출을 허용해야 하는가",
        pro_persona="미래역량 강조 교사",
        con_persona="기초학력 강조 교사",
    )
    assert len(payload["turns"]) == 6
    assert debate_has_stored_sources(payload)
    assert payload["topic_articles"] == DEMO_ARTICLES
    sources = find_turn_sources(payload, turn_id="pro-1")
    assert sources
    assert all(item.get("url") for item in sources)
    claims = [c for t in payload["turns"] for c in (t.get("claims") or [])]
    flawed = [c for c in claims if c.get("verdict") in {"false", "exaggerated"}]
    supported = [c for c in claims if c.get("verdict") == "supported"]
    assert len(flawed) >= 2
    assert len(supported) >= 4
