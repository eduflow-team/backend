"""도메인 전용 예외 정의.

서비스 레이어는 이 예외들만 발생시키고, 실제 HTTP 응답 변환은
`app.core.error_handlers`에 등록된 전역 핸들러가 담당한다.
"""

from fastapi import status


class DomainException(Exception):
    """도메인 규칙 위반 시 발생하는 예외의 베이스 클래스."""

    status_code: int = status.HTTP_500_INTERNAL_SERVER_ERROR
    default_message: str = "서버 내부 오류가 발생했습니다."

    def __init__(self, message: str | None = None) -> None:
        self.message = message or self.default_message
        super().__init__(self.message)


class InvalidSignupCodeError(DomainException):
    """교사 가입 인증 코드가 없거나 올바르지 않을 때 발생 (403)."""

    status_code = status.HTTP_403_FORBIDDEN
    default_message = "교사 가입 인증 코드가 올바르지 않습니다."


class EmailAlreadyExistsError(DomainException):
    """이미 가입된 이메일로 회원가입을 시도할 때 발생 (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_message = "이미 존재하는 이메일입니다."


class InvalidCredentialsError(DomainException):
    """가입되지 않은 이메일이거나 비밀번호가 일치하지 않을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "이메일 또는 비밀번호가 일치하지 않습니다."
