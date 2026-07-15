"""Stage 2 과제 API Request/Response 스키마 (Notion flat JSON)."""

from pydantic import BaseModel, Field, field_validator


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


class Step2HighlightSubmissionItem(BaseModel):
    highlighted_text: str = Field(..., min_length=1)
    student_error_type: str = Field(..., min_length=1)
    student_reason: str = Field(..., min_length=1)

    @field_validator("student_error_type")
    @classmethod
    def validate_error_type(cls, value: str) -> str:
        normalized = value.strip().upper()
        if normalized not in ALLOWED_HALLUCINATION_TYPES:
            raise ValueError("invalid student_error_type")
        return normalized


class Step2HighlightRequest(BaseModel):
    submissions: list[Step2HighlightSubmissionItem] = Field(..., min_length=1, max_length=1)


class Step2HighlightEvaluationReport(BaseModel):
    location_match_score: float
    error_type_match: bool
    reasoning_score: float
    ai_feedback: str


class Step2HighlightResultItem(BaseModel):
    highlighted_text: str
    student_error_type: str
    student_reason: str
    is_correct: bool
    evaluation_report: Step2HighlightEvaluationReport
    correct_answer: str | None = None
    correct_error_type: str | None = None


class Step2HighlightResponse(BaseModel):
    is_all_correct: bool
    highlight_phase_complete: bool
    remaining_errors_to_find: int
    results: list[Step2HighlightResultItem]
    attempts: Stage2AttemptsDetail
    cleared_highlights: list[str]


class Step2CorrectionItem(BaseModel):
    original_highlight: str = Field(..., min_length=1)
    student_answer: str = Field(..., min_length=1)


class Step2CorrectionRequest(BaseModel):
    corrections: list[Step2CorrectionItem] = Field(..., min_length=1)


class Step2CorrectionFeedbackDetail(BaseModel):
    student_found_error: str
    student_answer: str
    is_item_passed: bool
    hallucination_reason: str
    reference_evidence: str
    ai_feedback: str


class Step2CorrectionResponse(BaseModel):
    is_passed: bool
    score: int
    final_correct_sentence: str
    feedback_details: list[Step2CorrectionFeedbackDetail]
