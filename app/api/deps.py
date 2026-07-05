"""인증이 필요한 엔드포인트에서 공통으로 사용하는 FastAPI 의존성."""

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import InvalidTokenError
from app.core.security import decode_token

_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user_id(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> int:
    """`Authorization: Bearer {access_token}` 헤더를 검증해 user_id를 반환한다.

    헤더 누락·서명 오류·만료는 모두 동일하게 401(`InvalidTokenError`)로 처리한다.
    `/auth/logout`, `/auth/me`, `/auth/leave` 및 인증이 필요한 다른 도메인
    엔드포인트(예: 대시보드)가 공통으로 사용하는 의존성이다.
    """

    if credentials is None:
        raise InvalidTokenError()

    try:
        payload = decode_token(credentials.credentials)
    except jwt.PyJWTError as exc:
        raise InvalidTokenError() from exc

    if payload.get("type") != "access":
        raise InvalidTokenError()

    return int(payload["sub"])
