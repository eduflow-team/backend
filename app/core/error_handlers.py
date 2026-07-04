"""전역 예외 핸들러 등록.

모든 에러 응답은 FastAPI 표준 포맷 `{"detail": <str>}` 을 따른다.
"""

import logging

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.core.exceptions import DomainException

logger = logging.getLogger(__name__)

_FIELD_LABELS: dict[str, str] = {
    "email": "이메일",
    "password": "비밀번호",
    "name": "이름",
    "phone": "전화번호",
    "role": "role",
}

_SOCIAL_LOGIN_FIELDS = {"provider", "social_token"}


def _error_response(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(status_code=status_code, content={"detail": message})


def _build_validation_message(exc: RequestValidationError) -> str:
    """Pydantic 검증 에러 목록에서 명세서 포맷에 맞는 메시지 한 개를 구성한다."""

    for error in exc.errors():
        loc = error.get("loc", ())
        field = str(loc[-1]) if loc else ""
        error_type = error.get("type", "")

        if field == "email":
            return "유효하지 않은 이메일 형식입니다."

        if field in _SOCIAL_LOGIN_FIELDS:
            return "잘못된 요청 파라미터 또는 지원하지 않는 소셜 공급자입니다."

        if error_type == "missing":
            label = _FIELD_LABELS.get(field, field or "필드")
            return f"필수 필드({label})가 누락되었습니다."

        if field == "role":
            return "role 값은 'STUDENT' 또는 'TEACHER'만 허용됩니다."

    return "유효하지 않은 요청입니다."


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(RequestValidationError)
    async def validation_exception_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        message = _build_validation_message(exc)
        return _error_response(status.HTTP_400_BAD_REQUEST, message)

    @app.exception_handler(DomainException)
    async def domain_exception_handler(request: Request, exc: DomainException) -> JSONResponse:
        return _error_response(exc.status_code, exc.message)

    @app.exception_handler(Exception)
    async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled server error: %s", request.url.path)
        return _error_response(status.HTTP_500_INTERNAL_SERVER_ERROR, "서버 내부 오류가 발생했습니다.")
