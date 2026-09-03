"""시연용 고정 토론 — 한 주제만 Langflow/뉴스 검색 없이 완성본을 반환한다."""

from __future__ import annotations

from app.services.stage3_debate import balance_fact_claims, build_turns
from app.services.stage3_sources import link_claims_to_topic_articles

DEMO_TOPIC = "중고등학생의 AI 활용 과제 제출을 허용해야 하는가"

# 실제 접속 가능한 기사. 토론 근거·출처 모달과 1:1로 맞춘다.
DEMO_ARTICLES: list[dict] = [
    {
        "title": "올해부터 바뀌는 중고등학교 수행평가 AI 활용 지침, 미리 알아볼까요?",
        "url": "https://korea.kr/news/reporterView.do?newsId=148957866",
        "source": "대한민국 정책브리핑",
        "published": "",
        "kind": "기사",
    },
    {
        "title": "교육부, 취약계층·지역 학생에 AI 서비스 지원…교육 격차 줄인다",
        "url": "https://www.etnews.com/20260819000142",
        "source": "전자신문",
        "published": "",
        "kind": "기사",
    },
    {
        "title": "AI·디지털에 칼 빼든 뉴욕시…초·중학생 학교 내 AI 사용 금지",
        "url": "https://www.dongascience.com/news/79740",
        "source": "동아사이언스",
        "published": "",
        "kind": "기사",
    },
    {
        "title": "AI 글쓰기 잡는 무하유 'GPT킬러', 중·고등학교 이용 10배 확대",
        "url": "https://zdnet.co.kr/view/?no=20260122110457",
        "source": "ZDNet Korea",
        "published": "",
        "kind": "기사",
    },
]


def is_demo_topic(topic: str) -> bool:
    compact = (topic or "").replace(" ", "")
    return "AI활용과제" in compact and "허용" in compact


def build_demo_payload(
    *,
    topic: str,
    pro_persona: str,
    con_persona: str,
    question: str | None = None,
    mode: str = "v2",
) -> dict:
    extra = ""
    if question and question.strip():
        extra = f"\n추가 응답(학생 질문): {question.strip()}"

    pro_open = (
        "【입론 · 찬성 측】\n"
        f"주장 요약: AI는 이미 학습 도구이므로, 평가 방식을 바꾸면서 과제 활용을 허용해야 합니다. ({pro_persona})\n"
        "핵심 근거:\n"
        "1. 정부가 중고등학교 수행평가에서 생성형 AI를 어떻게 쓸지 지침을 마련해 학교 현장의 사용 기준을 정리하고 있습니다. [기사1]\n"
        "2. 교육부가 취약계층·지역 학생에게 AI 서비스를 지원해 교육 격차를 줄이려는 정책도 추진 중입니다. [기사2]\n"
        "3. AI 글쓰기 탐지 도구를 쓰는 중·고등학교가 크게 늘며, 금지보다 검증·규칙으로 대응하는 흐름이 나타나고 있습니다. [기사4]\n"
        f"{extra}"
    )
    con_open = (
        "【입론 · 반대 측】\n"
        f"주장 요약: AI에 의존하면 기초 사고력·글쓰기가 떨어지고 정확한 평가가 불가능합니다. ({con_persona})\n"
        "핵심 근거:\n"
        "1. 뉴욕시는 초·중학생의 학교 내 AI 사용을 금지하는 방향으로 움직이며, 의존 우려가 국제적으로 확산되고 있습니다. [기사3]\n"
        "2. 전국 중고등학교의 92%가 이미 AI 과제를 전면 허용했다는 조사 결과는 근거가 없습니다. [기사1]\n"
    )
    con_rebut = (
        "【반론 · 반대 측】\n"
        "주장 요약: 수행평가 AI 지침은 '숙제 대필 허용'과 같은 말이 아닙니다.\n"
        "핵심 근거:\n"
        "1. 정책브리핑의 지침은 수행평가에서 AI를 어떤 조건으로 쓸지 정리한 것이지, 과제 대필을 허용한다는 뜻이 아닙니다. [기사1]\n"
        "2. AI 글쓰기 탐지 이용이 급증했다는 보도는, 과제에 AI가 쓰이는 문제가 이미 크다는 반증입니다. [기사4]\n"
    )
    pro_rebut = (
        "【반론 · 찬성 측】\n"
        "주장 요약: 금지보다 과정 평가·출처 명시·탐지 도구를 함께 쓰는 쪽이 현실적입니다.\n"
        "핵심 근거:\n"
        "1. 국내에서는 수행평가 AI 활용 지침을 통해 규칙을 만들며 대응하고 있습니다. [기사1]\n"
        "2. 취약계층 AI 지원 정책은, 도구를 가르치지 않는 학교만 불리해질 수 있음을 보여 줍니다. [기사2]\n"
        "3. 탐지 도구 도입이 늘었다는 점은 허용과 검증을 병행할 수 있다는 신호입니다. [기사4]\n"
    )
    con_close = (
        "【최종 변론 · 반대 측】\n"
        "주장 요약: 리터러시 교육·탐지 도구와 과제 제출 허용은 분리해야 합니다.\n"
        "핵심 근거:\n"
        "1. 뉴욕의 학교 내 AI 금지는 어린 학습자의 의존·기초학력 저하를 경고합니다. [기사3]\n"
        "2. 지침이 있어도 집에서 하는 과제의 대필을 완전히 막기는 어렵습니다. [기사1]\n"
    )
    pro_close = (
        "【최종 변론 · 찬성 측】\n"
        "주장 요약: 금지하면 음성적 사용만 늘고, 공개된 활용 규칙을 만드는 편이 낫습니다.\n"
        "핵심 근거:\n"
        "1. 수행평가 AI 지침이 있는 만큼, 학교마다 활용 규칙을 공개하는 편이 낫습니다. [기사1]\n"
        "2. AI로 쓴 글은 교사 채점과 탐지 도구로 원작 여부를 100% 판별할 수 있으므로 과제 허용이 안전합니다. [기사4]\n"
    )

    speeches = {
        "pro_open": pro_open,
        "con_open": con_open,
        "con_rebut": con_rebut,
        "pro_rebut": pro_rebut,
        "con_rerebut": con_close,
        "pro_rerebut": pro_close,
    }
    fact = {
        "topic": topic,
        "pro_claims_checked": [
            {
                "claim": "정부가 중고등학교 수행평가에서 생성형 AI를 어떻게 쓸지 지침을 마련해 학교 현장의 사용 기준을 정리하고 있습니다. [기사1]",
                "verdict": "supported",
                "reason": "정책브리핑의 중고교 수행평가 AI 활용 지침 보도와 부합합니다.",
            },
            {
                "claim": "교육부가 취약계층·지역 학생에게 AI 서비스를 지원해 교육 격차를 줄이려는 정책도 추진 중입니다. [기사2]",
                "verdict": "supported",
                "reason": "교육부의 AI 서비스 지원·격차 완화 보도와 연결됩니다.",
            },
            {
                "claim": "AI 글쓰기 탐지 도구를 쓰는 중·고등학교가 크게 늘며, 금지보다 검증·규칙으로 대응하는 흐름이 나타나고 있습니다. [기사4]",
                "verdict": "supported",
                "reason": "중고교 AI 탐지 도구 이용 급증 보도와 부합합니다.",
            },
        ],
        "con_claims_checked": [
            {
                "claim": "뉴욕시는 초·중학생의 학교 내 AI 사용을 금지하는 방향으로 움직이며, 의존 우려가 국제적으로 확산되고 있습니다. [기사3]",
                "verdict": "supported",
                "reason": "뉴욕시 초·중학생 학교 내 AI 사용 금지 보도가 있습니다.",
            },
            {
                "claim": "전국 중고등학교의 92%가 이미 AI 과제를 전면 허용했다는 조사 결과는 근거가 없습니다. [기사1]",
                "verdict": "false",
                "reason": "기사1은 수행평가 AI 활용 지침이지, 전국 92% 허용 조사가 아닙니다.",
            },
        ],
        "rebuttal_claims_checked": [
            {
                "claim": "AI로 쓴 글은 교사 채점과 탐지 도구로 원작 여부를 100% 판별할 수 있으므로 과제 허용이 안전합니다. [기사4]",
                "verdict": "exaggerated",
                "reason": "기사4는 탐지 도구 이용이 늘었다는 내용이지, 100% 판별을 입증하지 않습니다.",
            },
            {
                "claim": "정책브리핑의 지침은 수행평가에서 AI를 어떤 조건으로 쓸지 정리한 것이지, 과제 대필을 허용한다는 뜻이 아닙니다. [기사1]",
                "verdict": "supported",
                "reason": "지침 보도의 취지와 과제 대필 허용을 구분한 타당한 지적입니다.",
            },
        ],
    }
    fact = balance_fact_claims(fact, speeches)
    rounds = [{"role": role, "text": text} for role, text in speeches.items()]
    payload = build_turns(
        rounds,
        fact,
        topic=topic,
        pro_role=pro_persona,
        con_role=con_persona,
        source="demo",
        mode=mode or "v2",
    )
    payload["topic_articles"] = list(DEMO_ARTICLES)
    link_claims_to_topic_articles(payload, DEMO_ARTICLES, force=True)
    payload["elapsed"] = 8.0
    return payload
