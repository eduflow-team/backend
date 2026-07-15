"""Stage 1 과제 API Request/Response 스키마 (Notion flat JSON)."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.core.config import settings


class Stage1Parameters(BaseModel):
    # 허용값은 settings.STAGE1_CHUNK_SIZE_PRESETS — 서비스에서 400으로 검증
    chunk_size: int
    top_k: int = Field(..., ge=1, le=50)
    temperature: float = Field(..., ge=0.0, le=1.0)


class Stage1ChatRequest(BaseModel):
    message: str = Field(..., min_length=1)
    parameters: Stage1Parameters

    @field_validator("message")
    @classmethod
    def strip_message(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("message는 비어 있을 수 없습니다.")
        return stripped


class RagProcessVisualization(BaseModel):
    total_chunks: int
    retrieved_chunks: int
    vector_search_score: float


class Stage1ChatResponse(BaseModel):
    ai_response: str
    rag_process_visualization: RagProcessVisualization


class Stage1SubmitRequest(BaseModel):
    final_parameters: Stage1Parameters
    selected_ai_response: str = Field(..., min_length=1)

    @field_validator("selected_ai_response")
    @classmethod
    def strip_response(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("selected_ai_response는 비어 있을 수 없습니다.")
        return stripped


class Stage1EvaluationReport(BaseModel):
    faithfulness_score: int
    relevance_score: int
    feedback: str


class Stage1AttemptsInfo(BaseModel):
    used_attempts: int
    remaining_attempts: int


class Stage1SubmitResponse(BaseModel):
    current_score: int
    highest_score: int
    is_highest_score: bool
    evaluation_report: Stage1EvaluationReport
    attempts: Stage1AttemptsInfo


class Stage1ParameterExplanations(BaseModel):
    chunk_size: str
    top_k: str
    temperature: str


class Stage1AttemptsDetail(BaseModel):
    max_attempts: int
    used_attempts: int
    remaining_attempts: int


class Stage1AssignmentDetailResponse(BaseModel):
    assignment_id: int
    question: str
    guideline: str
    parameter_explanations: Stage1ParameterExplanations
    default_parameters: Stage1Parameters
    attempts: Stage1AttemptsDetail
    highest_score: int | None = None
    best_parameters: Stage1Parameters | None = None


class Stage1CreateResponse(BaseModel):
    assignment_id: int
    created_at: datetime | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


PARAMETER_EXPLANATIONS = Stage1ParameterExplanations(
    chunk_size=(
        "업로드된 문서를 잘게 나누는 단위입니다. "
        f"허용 값: {', '.join(str(v) for v in settings.STAGE1_CHUNK_SIZE_PRESETS)}. "
        "너무 크면 관련 없는 내용이, 작으면 맥락이 잘릴 수 있습니다."
    ),
    top_k=(
        "검색된 청크 중 AI에게 넘겨주는 개수입니다. "
        "K가 낮으면 정보 부족, 높으면 노이즈가 섞입니다."
    ),
    temperature=(
        "AI 답변의 무작위성 정도입니다. "
        "값이 낮을수록 일관되고 정확한 답변을 생성합니다."
    ),
)
