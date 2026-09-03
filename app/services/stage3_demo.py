"""시연용 고정 토론 — 한 주제만 Langflow/뉴스 검색 없이 완성본을 반환한다."""

from __future__ import annotations

from app.services.stage3_debate import balance_fact_claims, build_turns
from app.services.stage3_sources import link_claims_to_topic_articles

DEMO_TOPIC = "중고등학생의 AI 활용 과제 제출을 허용해야 하는가"

DEMO_ARTICLES: list[dict] = [
    {
        "title": "인천교육청, AI 교육행정 혁신 추진단 출범",
        "url": "https://news.kbs.co.kr/news/pc/view/view.do?ncd=8321456",
        "source": "KBS 뉴스",
        "published": "Wed, 02 Sep 2026 14:00:00 GMT",
        "kind": "기사",
    },
    {
        "title": "마인드로직, 12만명 고교생 'AI 교육 격차 해소' 나서",
        "url": "https://www.asiae.co.kr/article/2026090308530000000",
        "source": "아시아경제",
        "published": "Thu, 03 Sep 2026 08:53:00 GMT",
        "kind": "기사",
    },
    {
        "title": "스마트폰 뺏더니 AI까지…美 뉴욕 초·중생 AI 금지령 세계로 확산",
        "url": "https://www.yna.co.kr/view/AKR20260902051600009",
        "source": "연합뉴스",
        "published": "Wed, 02 Sep 2026 20:00:43 GMT",
        "kind": "기사",
    },
    {
        "title": "한국 AI 교육·인재양성 경험, 세계은행 타고 개도국으로 확산",
        "url": "https://www.etnews.com/20260902000001",
        "source": "전자신문",
        "published": "Wed, 02 Sep 2026 10:00:00 GMT",
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
        "1. 인천교육청이 AI 교육행정 혁신 추진단을 출범해 학교 현장의 AI 활용을 제도화하고 있습니다. [기사1]\n"
        "2. 민간 프로그램이 고교생 12만 명을 대상으로 AI 교육 격차 해소에 나선 사례가 있습니다. [기사2]\n"
        "3. 세계은행이 한국의 AI 교육·인재양성 경험을 개도국에 전하는 흐름도 확인됩니다. [기사4]\n"
        f"{extra}"
    )
    con_open = (
        "【입론 · 반대 측】\n"
        f"주장 요약: 기초 사고력과 글쓰기 평가가 불가능해지므로 과제 제출에 AI를 허용하면 안 됩니다. ({con_persona})\n"
        "핵심 근거:\n"
        "1. 뉴욕시는 초·중생의 AI 사용을 금지하는 방향으로 움직이며, 의존 우려가 국제적으로 확산되고 있습니다. [기사3]\n"
        "2. 전국 중고등학교의 92%가 이미 AI 과제를 전면 허용했다는 조사 결과는 근거가 없습니다. [기사1]\n"
        "3. AI로 쓴 글은 교사 채점으로 원작 여부를 100% 판별할 수 있다는 주장은 과장입니다. [기사2]\n"
    )
    con_rebut = (
        "【반론 · 반대 측】\n"
        "주장 요약: 교육청 추진단과 민간 프로그램은 '과제 제출 허용'과 같은 말이 아닙니다.\n"
        "핵심 근거:\n"
        "1. 행정 혁신 추진단은 업무 효율화이지, 숙제 대필을 허용하는 정책이 아닙니다. [기사1]\n"
        "2. 격차 해소 프로그램은 도구 교육을 목표로 하며, 평가 왜곡 문제는 남습니다. [기사2]\n"
    )
    pro_rebut = (
        "【반론 · 찬성 측】\n"
        "주장 요약: 금지보다 과정 평가·출처 명시를 강화하는 쪽이 현실적입니다.\n"
        "핵심 근거:\n"
        "1. 해외 금지 움직임과 별개로, 국내에서는 교육 행정에 AI를 공식 도입하는 사례가 늘고 있습니다. [기사1]\n"
        "2. 격차 해소 사업은 소외 학생이 도구를 배우지 못하면 더 불리해진다는 점을 보여 줍니다. [기사2]\n"
        "3. 인재양성 경험을 해외로 전하는 흐름은 AI 리터러시를 미래 역량으로 본다는 신호입니다. [기사4]\n"
    )
    con_close = (
        "【최종 변론 · 반대 측】\n"
        "주장 요약: 리터러시 교육과 과제 제출 허용은 분리해야 합니다.\n"
        "핵심 근거:\n"
        "1. 뉴욕의 금지 논의는 어린 학습자의 의존·기초학력 저하를 경고합니다. [기사3]\n"
        "2. 과정 평가를 도입해도, 집에서 하는 과제는 대필을 막기 어렵습니다. [기사3]\n"
    )
    pro_close = (
        "【최종 변론 · 찬성 측】\n"
        "주장 요약: 금지하면 음성적 사용만 늘고, 공개된 활용 규칙을 만드는 편이 낫습니다.\n"
        "핵심 근거:\n"
        "1. 교육청 차원의 AI 행정 혁신은 현장 규칙을 만들 주체가 이미 있다는 뜻입니다. [기사1]\n"
        "2. 격차 해소와 인재양성 보도는, 도구를 가르치지 않는 학교만 불리해질 수 있음을 보여 줍니다. [기사2]\n"
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
                "claim": "인천교육청이 AI 교육행정 혁신 추진단을 출범해 학교 현장의 AI 활용을 제도화하고 있습니다. [기사1]",
                "verdict": "supported",
                "reason": "교육청이 추진단을 출범했다는 보도와 부합합니다.",
            },
            {
                "claim": "민간 프로그램이 고교생 12만 명을 대상으로 AI 교육 격차 해소에 나선 사례가 있습니다. [기사2]",
                "verdict": "supported",
                "reason": "고교생 대상 AI 교육 격차 해소 사업 보도와 연결됩니다.",
            },
            {
                "claim": "세계은행이 한국의 AI 교육·인재양성 경험을 개도국에 전하는 흐름도 확인됩니다. [기사4]",
                "verdict": "supported",
                "reason": "세계은행을 통한 경험 확산 보도가 있습니다.",
            },
        ],
        "con_claims_checked": [
            {
                "claim": "뉴욕시는 초·중생의 AI 사용을 금지하는 방향으로 움직이며, 의존 우려가 국제적으로 확산되고 있습니다. [기사3]",
                "verdict": "supported",
                "reason": "뉴욕 초·중생 AI 금지 관련 보도가 있습니다.",
            },
            {
                "claim": "전국 중고등학교의 92%가 이미 AI 과제를 전면 허용했다는 조사 결과는 근거가 없습니다. [기사1]",
                "verdict": "false",
                "reason": "전국 92% 허용이라는 수치는 제시된 기사에 없습니다. 학생이 잡아야 할 허위 근거입니다.",
            },
            {
                "claim": "AI로 쓴 글은 교사 채점으로 원작 여부를 100% 판별할 수 있다는 주장은 과장입니다. [기사2]",
                "verdict": "exaggerated",
                "reason": "100% 판별은 기사로 뒷받침되지 않는 과장입니다.",
            },
        ],
        "rebuttal_claims_checked": [
            {
                "claim": "행정 혁신 추진단은 업무 효율화이지, 숙제 대필을 허용하는 정책이 아닙니다. [기사1]",
                "verdict": "supported",
                "reason": "추진단 보도의 취지와 과제 제출 허용을 구분한 타당한 지적입니다.",
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
