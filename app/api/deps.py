"""인증이 필요한 엔드포인트에서 공통으로 사용하는 FastAPI 의존성."""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import DomainException, InvalidAccessTokenError, InvalidTokenError
from app.core.security import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


def _decode_access_token(
    credentials: HTTPAuthorizationCredentials | None,
    exception_cls: type[DomainException],
) -> int:
    """`Authorization: Bearer {access_token}` 헤더를 검증해 user_id를 반환한다.

    헤더 누락·서명 오류·만료는 모두 동일하게 `exception_cls`(401)로 처리한다.
    엔드포인트별 명세서 에러 메시지가 서로 달라, 호출부에서 예외 클래스를 지정한다.
    """

    if credentials is None:
        raise exception_cls()

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise exception_cls() from exc

    if payload.get("type") != "access":
        raise exception_cls()

    return int(payload["sub"])


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> int:
    """`POST /auth/logout` 전용 (예외: `InvalidTokenError`)."""

    return _decode_access_token(credentials, InvalidTokenError)


def get_current_user_id_for_me(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> int:
    """`GET /auth/me` 전용 (예외: `InvalidAccessTokenError`)."""

    return _decode_access_token(credentials, InvalidAccessTokenError)
