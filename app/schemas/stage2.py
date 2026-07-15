"""Stage 2 과제 API Request/Response 스키마 (Notion flat JSON)."""

from pydantic import BaseModel, Field


ALLOWED_HALLUCINATION_TYPES = frozenset(
    {"PERSONA_BIAS", "INFORMATION_FABRICATION", "RETRIEVAL_ERROR"}
)


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
