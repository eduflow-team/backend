"""비밀번호 해시 및 JWT 토큰 발급 관련 유틸리티."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Literal

import bcrypt
import jwt

from app.core.config import settings

_ENCODING = "utf-8"


def hash_password(plain_password: str) -> str:
    salt = bcrypt.gensalt()
    hashed = bcrypt.hashpw(plain_password.encode(_ENCODING), salt)
    return hashed.decode(_ENCODING)


def verify_password(plain_password: str, password_hash: str) -> bool:
    return bcrypt.checkpw(plain_password.encode(_ENCODING), password_hash.encode(_ENCODING))


def _create_token(
    user_id: int,
    token_type: Literal["access", "refresh"],
    expires_delta: timedelta,
) -> tuple[str, datetime]:
    expires_at = datetime.now(UTC) + expires_delta
    payload = {
        "sub": str(user_id),
        "type": token_type,
        "exp": expires_at,
        "iat": datetime.now(UTC),
        # exp/iat는 초 단위로 잘려 인코딩되므로, jti가 없으면 같은 사용자에게 같은
        # 종류의 토큰을 1초 내 연속 발급할 때 완전히 동일한 문자열이 나올 수 있다
        # (refresh_tokens.refresh_token 중복 → RTR 조회 시 MultipleResultsFound).
        "jti": uuid.uuid4().hex,
    }
    token = jwt.encode(payload, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
    return token, expires_at


def create_access_token(user_id: int) -> tuple[str, datetime]:
    """액세스 토큰과 만료 시각(UTC)을 함께 반환한다."""

    return _create_token(
        user_id, "access", timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES)
    )


def create_refresh_token(user_id: int) -> tuple[str, datetime]:
    """리프레시 토큰과 만료 시각(UTC)을 함께 반환한다."""

    return _create_token(
        user_id, "refresh", timedelta(minutes=settings.REFRESH_TOKEN_EXPIRE_MINUTES)
    )


def decode_token(token: str) -> dict:
    """JWT를 디코딩해 payload를 반환한다.

    서명 불일치·만료 등 검증 실패 시 `jwt.PyJWTError`를 그대로 전파하며,
    HTTP 응답으로의 변환은 호출부(API 의존성)에서 담당한다.
    """

    return jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
