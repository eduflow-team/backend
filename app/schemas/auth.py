"""회원가입 / 학급 목록 조회 API의 Pydantic 요청·응답 스키마."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, EmailStr, Field, field_serializer


class SignupRequest(BaseModel):
    """POST /auth/signup 요청 바디.

    이메일 형식·필수 필드 누락 검증은 Pydantic이 라우터 진입 전(=비즈니스 로직 진입 전)
    단계에서 수행하며, 검증 실패는 `RequestValidationError`로 전역 핸들러가 400으로 변환한다.
    """

    email: EmailStr
    name: str = Field(..., min_length=1)
    phone: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)
    role: Literal["STUDENT", "TEACHER"]
    class_id: int | None = None
    signup_code: str | None = None


class SignupResponse(BaseModel):
    """POST /auth/signup 성공 응답.

    Envelope(status/message/data) 없이 생성된 리소스를 그대로 반환한다.
    """

    user_id: int
    email: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, value: datetime) -> str:
        return value.strftime("%Y-%m-%dT%H:%M:%S")


class ClassItem(BaseModel):
    class_id: int
    grade: int | None
    class_number: int | None


class ClassListResponse(BaseModel):
    """GET /auth/classes 성공 응답."""

    classes: list[ClassItem]


class ErrorDetail(BaseModel):
    """에러 응답 포맷 (FastAPI 표준). 400 / 403 / 409 / 500 공통."""

    detail: str
