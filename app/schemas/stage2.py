"""Stage 2 과제 API Request/Response 스키마 (Notion flat JSON)."""

from pydantic import BaseModel, Field


ALLOWED_HALLUCINATION_TYPES = frozenset(
    {"PERSONA_BIAS", "INFORMATION_FABRICATION", "RETRIEVAL_ERROR"}
)

HALLUCINATION_TYPE_OPTIONS: list[dict[str, str]] = [
    {
        "value": "PERSONA_BIAS",
        "label": "페르소나 편향",
        "description": "잘못된 믿음을 가진 AI가 답변을 조작",
    },
    {
        "value": "INFORMATION_FABRICATION",
        "label": "정보 날조",
        "description": "교재에 없는 허위 사실을 생성",
    },
    {
        "value": "RETRIEVAL_ERROR",
        "label": "잘못된 문서 검색",
        "description": "무관한 청크를 참고하여 오류 발생",
    },
]


class HallucinationTypeOption(BaseModel):
    value: str
    label: str
    description: str


class Stage2AttemptsDetail(BaseModel):
    max_attempts: int
    used_attempts: int
    remaining_attempts: int


class Stage2AssignmentDetailResponse(BaseModel):
    assignment_id: int
    title: str
    reference_document_text: str
    question: str
    flawed_ai_response: str
    expected_error_count: int
    hallucination_type_options: list[HallucinationTypeOption]
    hallucination_type_hints: list[str]
    status: str
    highlight_phase_complete: bool
    remaining_errors_to_find: int
    attempts: Stage2AttemptsDetail
    cleared_highlights: list[str]


class Stage2GeneratedErrorItem(BaseModel):
    answer_id: int
    error_sentence: str
    error_type: str
    start_index: int
    end_index: int
    correct_sentence: str
    hallucination_reason: str
    evidence_sentence: str


class Stage2CreateResponse(BaseModel):
    assignment_id: int
    title: str
    question: str
    flawed_ai_response: str
    expected_error_count: int
    generated_errors: list[Stage2GeneratedErrorItem]
