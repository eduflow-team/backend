"""소셜 로그인 제공자별 토큰 검증 클라이언트.

각 클라이언트는 사용자가 보낸 `social_token`을 해당 플랫폼에 직접 질의해 검증하고,
검증에 성공하면 해당 플랫폼에서의 사용자 고유 식별자(social_id)를 반환한다.

- 토큰이 없거나 위조/만료된 경우: `InvalidSocialTokenError` (401)
- 플랫폼 서버 통신 실패(네트워크 오류, 5xx 등): `SocialAuthServiceUnavailableError` (502)
"""

from abc import ABC, abstractmethod

import httpx
import jwt

from app.core.exceptions import InvalidSocialTokenError, SocialAuthServiceUnavailableError
from app.schemas.auth import SocialProvider

_REQUEST_TIMEOUT_SECONDS = 5.0


class SocialAuthClient(ABC):
    @abstractmethod
    async def get_social_id(self, social_token: str) -> str:
        """소셜 토큰을 검증하고 플랫폼 고유 사용자 ID를 반환한다."""


class KakaoAuthClient(SocialAuthClient):
    _USER_INFO_URL = "https://kapi.kakao.com/v2/user/me"

    async def get_social_id(self, social_token: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    self._USER_INFO_URL,
                    headers={"Authorization": f"Bearer {social_token}"},
                )
        except httpx.HTTPError as exc:
            raise SocialAuthServiceUnavailableError() from exc

        if response.status_code in (401, 403):
            raise InvalidSocialTokenError()
        if response.status_code != 200:
            raise SocialAuthServiceUnavailableError()

        social_id = response.json().get("id")
        if social_id is None:
            raise InvalidSocialTokenError()
        return str(social_id)


class GoogleAuthClient(SocialAuthClient):
    _TOKEN_INFO_URL = "https://www.googleapis.com/oauth2/v3/tokeninfo"

    async def get_social_id(self, social_token: str) -> str:
        try:
            async with httpx.AsyncClient(timeout=_REQUEST_TIMEOUT_SECONDS) as client:
                response = await client.get(
                    self._TOKEN_INFO_URL, params={"access_token": social_token}
                )
        except httpx.HTTPError as exc:
            raise SocialAuthServiceUnavailableError() from exc

        # 구글 tokeninfo는 유효하지 않은 토큰에 대해 400을 반환하지만,
        # 우리 API 계약상 "토큰 검증 실패"는 401로 일원화한다.
        if response.status_code != 200:
            raise InvalidSocialTokenError()

        social_id = response.json().get("sub")
        if social_id is None:
            raise InvalidSocialTokenError()
        return str(social_id)


class AppleAuthClient(SocialAuthClient):
    """Apple ID Token(JWT) 서명을 Apple 공개키(JWKS)로 검증한다.

    실제 프로덕션에서는 `aud`(클라이언트 ID) 검증도 추가해야 하지만,
    앱 등록 정보가 아직 없는 현재 범위에서는 서명·만료만 검증한다.
    """

    _JWKS_URL = "https://appleid.apple.com/auth/keys"

    async def get_social_id(self, social_token: str) -> str:
        try:
            jwk_client = jwt.PyJWKClient(self._JWKS_URL, timeout=_REQUEST_TIMEOUT_SECONDS)
            signing_key = jwk_client.get_signing_key_from_jwt(social_token)
        except jwt.PyJWKClientConnectionError as exc:
            raise SocialAuthServiceUnavailableError() from exc
        except jwt.InvalidTokenError as exc:
            raise InvalidSocialTokenError() from exc

        try:
            payload = jwt.decode(
                social_token,
                signing_key.key,
                algorithms=["RS256"],
                options={"verify_aud": False},
            )
        except jwt.InvalidTokenError as exc:
            raise InvalidSocialTokenError() from exc

        social_id = payload.get("sub")
        if social_id is None:
            raise InvalidSocialTokenError()
        return str(social_id)


_CLIENTS: dict[SocialProvider, type[SocialAuthClient]] = {
    SocialProvider.KAKAO: KakaoAuthClient,
    SocialProvider.GOOGLE: GoogleAuthClient,
    SocialProvider.APPLE: AppleAuthClient,
}


def get_social_auth_client(provider: SocialProvider) -> SocialAuthClient:
    return _CLIENTS[provider]()
