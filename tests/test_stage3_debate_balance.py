from app.services.stage3_debate import (
    balance_fact_claims,
    count_flaw_claims,
    count_supported_claims,
)


def test_balance_fact_claims_downgrades_excess_flaws() -> None:
    fact = {
        "pro_claims_checked": [
            {"claim": "A1", "verdict": "exaggerated", "reason": "r1"},
            {"claim": "A2", "verdict": "unsupported", "reason": "r2"},
            {"claim": "A3", "verdict": "false", "reason": "r3"},
            {"claim": "A4", "verdict": "exaggerated", "reason": "r4"},
        ],
        "con_claims_checked": [],
    }
    balanced = balance_fact_claims(fact) or {}
    assert count_flaw_claims(balanced) == 3
    assert count_supported_claims(balanced) >= 1


def test_balance_fact_claims_adds_supported_from_speeches() -> None:
    fact = {
        "pro_claims_checked": [
            {
                "claim": "AI세는 기본소득 재원으로 쓰일 수 있습니다.",
                "verdict": "exaggerated",
                "reason": "출처 없음",
            }
        ],
        "con_claims_checked": [
            {
                "claim": "로봇세는 혁신을 막는다는 주장만으로는 부족합니다.",
                "verdict": "unsupported",
                "reason": "근거 부족",
            }
        ],
    }
    speeches = {
        "pro_open": (
            "【찬성 입장】\n주장 요약: AI세 도입 찬성\n"
            "핵심 근거:\n"
            "1. 자동화 확대에 따른 세수 공백을 메울 수 있습니다.\n"
            "2. 재분배 정책의 재원으로 활용할 수 있습니다.\n"
        ),
        "con_open": (
            "【반대 입장】\n주장 요약: AI세 도입 반대\n"
            "핵심 근거:\n"
            "1. 기업 투자를 위축시킬 수 있습니다.\n"
            "2. 국제 경쟁력 저하 우려가 있습니다.\n"
        ),
    }
    balanced = balance_fact_claims(fact, speeches) or {}
    assert count_flaw_claims(balanced) == 2
    assert count_supported_claims(balanced) >= 4
