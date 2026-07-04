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


class InvalidSocialTokenError(DomainException):
    """소셜 토큰이 만료됐거나 위조되어 검증에 실패했을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "만료되었거나 유효하지 않은 소셜 토큰입니다."


class SocialAuthServiceUnavailableError(DomainException):
    """소셜 인증 서버(카카오/구글/애플)와의 통신에 실패했을 때 발생 (502)."""

    status_code = status.HTTP_502_BAD_GATEWAY
    default_message = "소셜 인증 서버와의 통신에 실패했습니다."


class SocialAccountNotFoundError(DomainException):
    """소셜 토큰은 유효하나, 연동된 계정이 없을 때 발생 (404). 회원가입 유도용."""

    status_code = status.HTTP_404_NOT_FOUND
    default_message = "등록되지 않은 사용자입니다. 회원가입이 필요합니다."


class SocialAccountAlreadyExistsError(DomainException):
    """이미 연동된 소셜 계정(provider + social_id)으로 재가입을 시도할 때 발생 (409)."""

    status_code = status.HTTP_409_CONFLICT
    default_message = "이미 가입된 소셜 계정입니다."


class InvalidTokenError(DomainException):
    """Access/Refresh Token이 없거나 서명이 유효하지 않거나 이미 만료·무효화됐을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "유효하지 않거나 이미 만료된 토큰입니다."


class InvalidRefreshTokenError(DomainException):
    """POST /auth/refresh 전용: Refresh Token 서명 불일치·만료·재사용(RTR 위반) 시 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "Refresh Token이 만료되었거나 유효하지 않습니다. 다시 로그인해 주세요."


class InvalidAccessTokenError(DomainException):
    """GET /auth/me 전용: Access Token이 없거나 서명이 유효하지 않거나 만료됐을 때 발생 (401)."""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_message = "인증 토큰(Access Token)이 누락되었거나 만료되었습니다."
