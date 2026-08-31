"""Stage 3 발언 매핑·채점 단위 테스트 (DB 불필요)."""

from app.clients.stage3_langflow_client import Stage3LangflowClient
from app.services.stage3_debate import (
    attach_claims,
    build_turns,
    grade_usage,
    overlap_ratio,
    parse_speech,
    public_turns,
    resolve_checked_turn_ids,
    turn_needs_check,
)


def test_parse_speech():
    text = """【찬성 입장】
주장 요약: 시험 감독에 AI를 도입해야 합니다.
핵심 근거:
1. 부정행위가 90% 줄었다.
2. 교사 시간을 아낄 수 있다.
예상 효과: 공정성 향상
"""
    summary, grounds = parse_speech(text)
    assert "시험 감독" in summary
    assert len(grounds) == 2
    assert "90%" in grounds[0]


def test_overlap_and_attach():
    turns = [
        {
            "id": "pro-1",
            "side": "pro",
            "text": "AI 감독을 도입해야 한다",
            "claim": "부정행위가 90% 줄었다",
            "raw": "부정행위가 90% 줄었다",
            "claims": [],
        },
        {
            "id": "con-1",
            "side": "con",
            "text": "개인정보 침해가 문제다",
            "claim": "민감정보는 별도 동의가 필요하다",
            "raw": "민감정보는 별도 동의가 필요하다",
            "claims": [],
        },
        {
            "id": "pro-2",
            "side": "pro",
            "text": "동의 절차를 넣으면 된다",
            "claim": "교사 시간을 아낄 수 있다",
            "raw": "교사 시간을 아낄 수 있다",
            "claims": [],
        },
    ]
    fact = {
        "pro_claims_checked": [
            {"claim": "부정행위가 90% 줄었다", "verdict": "exaggerated", "reason": "과장"},
            {"claim": "교사 시간을 아낄 수 있다", "verdict": "supported", "reason": "가능"},
        ],
        "con_claims_checked": [
            {"claim": "민감정보는 별도 동의가 필요하다", "verdict": "supported", "reason": "맞음"},
        ],
    }
    attach_claims(turns, fact)
    assert turns[0]["verdict"] == "exaggerated"
    assert turns[1]["verdict"] == "supported"
    assert turns[2]["verdict"] == "supported"
    assert overlap_ratio("부정행위가 90% 줄었다", "부정행위가 90% 줄었다") == 1.0


def test_build_turns_skips_empty():
    rounds = [
        {"role": "pro", "text": "주장 요약: 도입하자\n핵심 근거:\n1. 빠르다"},
        {"role": "con", "text": ""},
        {"role": "rebut", "text": "주장 요약: 그래도 도입\n보강 근거:\n1. 동의 받는다"},
    ]
    out = build_turns(rounds, None, topic="주제", pro_role="p", con_role="c")
    assert [turn["id"] for turn in out["turns"]] == ["pro-1", "pro-2"]
    assert out["turns"][0]["verdict"] == "supported"


def test_grade_usage():
    turns = [
        {"id": "pro-1", "side": "pro", "round": "1", "text": "a", "claim": "a", "verdict": "exaggerated", "why": "", "claims": [{"verdict": "exaggerated"}]},
        {"id": "con-1", "side": "con", "round": "1", "text": "b", "claim": "b", "verdict": "supported", "why": "", "claims": [{"verdict": "supported"}]},
        {"id": "pro-2", "side": "pro", "round": "2", "text": "c", "claim": "c", "verdict": "supported", "why": "", "claims": []},
    ]
    report = grade_usage(turns, {"pro-1"})
    assert report["caught"] == 1
    assert report["passed"] == 2
    assert report["missed"] == 0
    assert report["wasted"] == 0
    assert report["score"] == 100

    missed = grade_usage(turns, set())
    assert missed["missed"] == 1
    assert missed["passed"] == 2
    assert missed["score"] == 67

    wasted = grade_usage(turns, {"pro-1", "con-1"})
    assert wasted["caught"] == 1
    assert wasted["wasted"] == 1
    assert wasted["passed"] == 1
    assert wasted["score"] == 67
    assert turn_needs_check(turns[0]) is True
    assert turn_needs_check(turns[1]) is False


def test_public_turns_hides_verdict():
    turns = [
        {
            "id": "pro-1",
            "side": "pro",
            "round": "1라운드 · 주장",
            "text": "도입하자",
            "claim": "90%",
            "grounds": ["90%"],
            "verdict": "exaggerated",
            "why": "과장",
            "claims": [{"claim": "90%", "verdict": "exaggerated", "reason": "과장"}],
        }
    ]
    hidden = public_turns(turns, set())
    assert "verdict" not in hidden[0]
    assert "why" not in hidden[0]
    revealed = public_turns(turns, {"pro-1"})
    assert revealed[0]["verdict"] == "exaggerated"


def test_resolve_checked_turn_ids():
    turns = [
        {"id": "pro-1"},
        {"id": "con-1"},
        {"id": "pro-2"},
    ]

    class Decision:
        def __init__(self, turn_id: str, checked: bool) -> None:
            self.turn_id = turn_id
            self.checked = checked

    assert resolve_checked_turn_ids(turns, {"pro-1"}, None) == {"pro-1"}
    assert resolve_checked_turn_ids(turns, {"pro-1"}, []) == {"pro-1"}
    assert resolve_checked_turn_ids(
        turns,
        set(),
        [Decision("pro-1", True), Decision("con-1", False)],
    ) == {"pro-1"}


def test_parse_stage3_component_ids():
    payload = {
        "outputs": [
            {
                "outputs": [
                    {
                        "component_id": "ChatOutput-v2pro",
                        "results": {"message": {"text": "찬성 주장"}},
                    },
                    {
                        "component_id": "ChatOutput-v2con",
                        "results": {"message": {"text": "반대 반박"}},
                    },
                    {
                        "component_id": "ChatOutput-v2rebut",
                        "results": {"message": {"text": "재반박"}},
                    },
                    {
                        "component_id": "ChatOutput-v2fact",
                        "results": {
                            "message": {
                                "text": '```json\n{"pro_claims_checked": []}\n```'
                            }
                        },
                    },
                ]
            }
        ]
    }
    result = Stage3LangflowClient().parse_outputs(payload)
    assert result.pro_argument == "찬성 주장"
    assert result.con_argument == "반대 반박"
    assert result.rebuttal_argument == "재반박"
    assert "pro_claims_checked" in result.fact_check


if __name__ == "__main__":
    test_parse_speech()
    test_overlap_and_attach()
    test_build_turns_skips_empty()
    test_grade_usage()
    test_public_turns_hides_verdict()
    test_resolve_checked_turn_ids()
    test_parse_stage3_component_ids()
    print("OK")
