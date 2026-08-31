"""Stage 1 과제 API Request/Response 스키마 (퀴즈 1문제 + 리소스 감점)."""

from datetime import datetime

from pydantic import BaseModel, Field, field_serializer, field_validator

from app.core.config import settings
from app.core.datetime_utils import serialize_utc_z


class Stage1Parameters(BaseModel):
    # 허용값은 settings.STAGE1_CHUNK_SIZE_PRESETS — 서비스에서 검증
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
    # 학생이 근거를 확인할 수 있도록 검색된 청크 본문(유사도 높은 순)
    retrieved_chunk_previews: list[str] = Field(default_factory=list)
    # top_k × chunk_size 대략치 (토큰/비용 감 잡이용 프록시)
    approx_context_chars: int = 0


class Stage1ChatResponse(BaseModel):
    ai_response: str
    rag_process_visualization: RagProcessVisualization


class Stage1SubmitRequest(BaseModel):
    final_parameters: Stage1Parameters
    student_answer: str = Field(..., min_length=1)

    @field_validator("student_answer")
    @classmethod
    def strip_student_answer(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("student_answer는 비어 있을 수 없습니다.")
        min_chars = int(settings.STAGE1_MIN_STUDENT_ANSWER_CHARS)
        if len(stripped) < min_chars:
            raise ValueError(f"답안은 {min_chars}자 이상 작성해 주세요.")
        return stripped


class Stage1KeypointResult(BaseModel):
    index: int
    keypoint: str
    matched: bool


class Stage1EvaluationReport(BaseModel):
    is_correct: bool
    correct_score: int
    resource_penalty: int
    feedback: str
    matched_keypoints: int = 0
    total_keypoints: int = 0
    keypoint_results: list[Stage1KeypointResult] = Field(default_factory=list)


class Stage1AttemptsInfo(BaseModel):
    used_attempts: int
    remaining_attempts: int


class Stage1AttemptSummary(BaseModel):
    attempt_number: int
    score: int
    is_correct: bool
    correct_score: int
    resource_penalty: int
    feedback: str
    student_answer: str
    parameters: Stage1Parameters
    is_final: bool = False
    matched_keypoints: int = 0
    total_keypoints: int = 0
    keypoint_results: list[Stage1KeypointResult] = Field(default_factory=list)


class Stage1SubmitResponse(BaseModel):
    current_score: int
    highest_score: int
    is_highest_score: bool
    is_correct: bool
    evaluation_report: Stage1EvaluationReport
    attempts: Stage1AttemptsInfo
    attempt_summaries: list[Stage1AttemptSummary] = Field(default_factory=list)
    is_finalized: bool = False
    # 마감 후에만 정답 문자열 포함
    correct_answer: str | None = None


class Stage1FinalizeRequest(BaseModel):
    attempt_number: int = Field(..., ge=1)


class Stage1FinalizeResponse(BaseModel):
    attempt_number: int
    current_score: int
    highest_score: int
    is_correct: bool
    evaluation_report: Stage1EvaluationReport
    attempts: Stage1AttemptsInfo
    attempt_summaries: list[Stage1AttemptSummary] = Field(default_factory=list)
    is_finalized: bool = True
    correct_answer: str | None = None


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
    due_at: datetime | None = None
    parameter_explanations: Stage1ParameterExplanations
    default_parameters: Stage1Parameters
    attempts: Stage1AttemptsDetail
    attempt_summaries: list[Stage1AttemptSummary] = Field(default_factory=list)
    is_finalized: bool = False
    final_attempt_number: int | None = None
    highest_score: int | None = None
    best_parameters: Stage1Parameters | None = None
    document_filename: str | None = None
    document_url: str | None = None
    document_text: str | None = None
    # 마감 전 False. True일 때만 correct_answer 채움
    is_answer_revealed: bool = False
    correct_answer: str | None = None
    answer_keypoints: list[str] | None = None
    answer_keypoint_count: int = Field(default=3)

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return serialize_utc_z(value)


class Stage1CreateResponse(BaseModel):
    assignment_id: int
    created_at: datetime | None
    due_at: datetime | None
    question: str

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        return serialize_utc_z(value)

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        return serialize_utc_z(value)


PARAMETER_EXPLANATIONS = Stage1ParameterExplanations(
    chunk_size=(
        "업로드된 문서를 잘게 나누는 단위입니다. "
        f"허용 값: {', '.join(str(v) for v in settings.STAGE1_CHUNK_SIZE_PRESETS)}. "
        "너무 크면 관련 없는 내용이, 작으면 맥락이 잘릴 수 있습니다."
    ),
    top_k=(
        "검색된 청크 중 AI에게 넘겨주는 개수입니다. "
        "K가 낮으면 정보 부족, 높으면 노이즈가 섞입니다. "
        "기본값보다 크게 올리면 맞더라도 감점될 수 있습니다."
    ),
    temperature=(
        "AI 답변의 무작위성 정도입니다. "
        "값이 낮을수록 일관된 답변을 생성합니다. (채점 감점에는 사용하지 않습니다.)"
    ),
)
