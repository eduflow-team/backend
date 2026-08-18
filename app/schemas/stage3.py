"""Stage 3 과제 API Request/Response 스키마."""

from datetime import UTC, datetime

from pydantic import BaseModel, Field, field_serializer, field_validator

ALLOWED_DEBATE_MODES = frozenset({"v1", "v2"})


class Stage3AttemptsDetail(BaseModel):
    max_attempts: int
    used_attempts: int
    remaining_attempts: int


class Stage3Claim(BaseModel):
    claim: str
    verdict: str
    reason: str = ""


class Stage3TurnPublic(BaseModel):
    id: str
    side: str
    round: str
    text: str
    claim: str
    grounds: list[str] = Field(default_factory=list)
    verdict: str | None = None
    why: str | None = None
    claims: list[Stage3Claim] | None = None


class Stage3Speaker(BaseModel):
    name: str
    role: str


class Stage3DebatePublicPayload(BaseModel):
    topic: str
    source: str
    mode: str
    elapsed: float | None = None
    pro: Stage3Speaker
    con: Stage3Speaker
    turns: list[Stage3TurnPublic]


class Stage3CreateRequest(BaseModel):
    class_id: int
    topic: str = Field(..., min_length=1)
    pro_persona: str = Field(..., min_length=1, max_length=100)
    con_persona: str = Field(..., min_length=1, max_length=100)
    fact_persona: str | None = Field(default=None, max_length=100)
    title: str | None = None
    subject: str | None = None
    debate_mode: str = "v2"
    due_at: str | None = None

    @field_validator("topic", "pro_persona", "con_persona")
    @classmethod
    def strip_required_text(cls, value: str) -> str:
        return (value or "").strip()

    @field_validator("title", "subject", "fact_persona")
    @classmethod
    def strip_optional_text(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None

    @field_validator("debate_mode")
    @classmethod
    def validate_mode(cls, value: str) -> str:
        mode = (value or "v2").strip().lower()
        if mode not in ALLOWED_DEBATE_MODES:
            raise ValueError("debate_mode는 v1 또는 v2만 허용됩니다.")
        return mode


class Stage3CreateResponse(BaseModel):
    assignment_id: int
    title: str | None
    topic: str
    debate_mode: str
    created_at: datetime | None

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Stage3AssignmentDetailResponse(BaseModel):
    assignment_id: int
    title: str | None
    topic: str
    question: str | None
    pro_persona: str
    con_persona: str
    fact_persona: str | None
    debate_mode: str
    status: str
    debate_started: bool
    submitted: bool
    attempts: Stage3AttemptsDetail
    highest_score: int | None = None
    due_at: datetime | None = None
    debate: Stage3DebatePublicPayload | None = None

    @field_serializer("due_at")
    def serialize_due_at(self, value: datetime | None) -> str | None:
        if value is None:
            return None
        return value.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


class Stage3DebateRequest(BaseModel):
    question: str | None = None

    @field_validator("question")
    @classmethod
    def strip_question(cls, value: str | None) -> str | None:
        if value is None:
            return None
        stripped = value.strip()
        return stripped or None


class Stage3DebateResponse(BaseModel):
    assignment_id: int
    attempt_id: int
    attempt_number: int
    reused: bool
    debate: Stage3DebatePublicPayload
    attempts: Stage3AttemptsDetail


class Stage3FactcheckRequest(BaseModel):
    turn_id: str = Field(..., min_length=1)

    @field_validator("turn_id")
    @classmethod
    def strip_turn_id(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("turn_id는 비어 있을 수 없습니다.")
        return stripped


class Stage3FactcheckResponse(BaseModel):
    turn_id: str
    verdict: str
    why: str
    claims: list[Stage3Claim] = Field(default_factory=list)


class Stage3DecisionItem(BaseModel):
    turn_id: str = Field(..., min_length=1)
    checked: bool

    @field_validator("turn_id")
    @classmethod
    def strip_turn_id(cls, value: str) -> str:
        return value.strip()


class Stage3SubmitRequest(BaseModel):
    decisions: list[Stage3DecisionItem] | None = None


class Stage3GradeRow(BaseModel):
    id: str
    side: str
    round: str | None = None
    text: str
    claim: str
    verdict: str
    why: str
    checked: bool
    suspicious: bool
    outcome: str


class Stage3SubmitResponse(BaseModel):
    current_score: int
    highest_score: int
    is_highest_score: bool
    caught: int
    passed: int
    missed: int
    wasted: int
    headline: str
    advice: str
    rows: list[Stage3GradeRow]
    attempts: Stage3AttemptsDetail
