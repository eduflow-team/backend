"""회원가입 / 로그인 관련 비즈니스 로직."""

from datetime import UTC, datetime

import jwt
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidRefreshTokenError,
    InvalidSignupCodeError,
    InvalidTokenError,
    SocialAccountAlreadyExistsError,
    SocialAccountNotFoundError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    hash_password,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.schemas.auth import LoginRequest, SignupRequest, SocialProvider, SocialSignupRequest
from app.services.social_auth_clients import get_social_auth_client


class AuthTokens:
    """로그인 성공 시 발급되는 사용자·토큰 정보 묶음."""

    def __init__(self, user: User, access_token: str, refresh_token: str, expires_in: int) -> None:
        self.user = user
        self.access_token = access_token
        self.refresh_token = refresh_token
        self.expires_in = expires_in


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.refresh_token_repository = RefreshTokenRepository(session)

    async def login(self, payload: LoginRequest) -> AuthTokens:
        user = await self.user_repository.get_by_email(payload.email)
        if user is None or not user.password_hash:
            raise InvalidCredentialsError()

        if not verify_password(payload.password, user.password_hash):
            raise InvalidCredentialsError()

        return await self._issue_tokens(user)

    async def social_login(self, provider: SocialProvider, social_token: str) -> AuthTokens:
        client = get_social_auth_client(provider)
        social_id = await client.get_social_id(social_token)

        user = await self.user_repository.get_by_social_id(provider.value, social_id)
        if user is None:
            # 토큰 자체는 유효하므로, 연동된 계정이 없다는 사실을 그대로 알려
            # 프론트가 소셜 회원가입 화면으로 유도할 수 있게 한다.
            raise SocialAccountNotFoundError()

        return await self._issue_tokens(user)

    async def social_signup(self, provider: SocialProvider, payload: SocialSignupRequest) -> AuthTokens:
        if payload.role == "TEACHER":
            self._validate_teacher_signup_code(payload.signup_code)

        client = get_social_auth_client(provider)
        social_id = await client.get_social_id(payload.social_token)

        existing_user = await self.user_repository.get_by_social_id(provider.value, social_id)
        if existing_user is not None:
            raise SocialAccountAlreadyExistsError()

        user = User(
            social_provider=provider.value,
            social_id=social_id,
            name=payload.name,
            phone=payload.phone,
            role=payload.role,
            class_id=payload.class_id,
        )
        user = await self.user_repository.create(user)
        await self.session.commit()

        return await self._issue_tokens(user)

    async def _issue_tokens(self, user: User) -> AuthTokens:
        access_token, access_expires_at = create_access_token(user.user_id)
        refresh_token, refresh_expires_at = create_refresh_token(user.user_id)

        await self.refresh_token_repository.create(
            RefreshToken(
                user_id=user.user_id,
                refresh_token=refresh_token,
                expires_at=refresh_expires_at,
            )
        )
        await self.session.commit()

        expires_in = int((access_expires_at - datetime.now(UTC)).total_seconds())
        return AuthTokens(
            user=user,
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=expires_in,
        )

    async def logout(self, user_id: int, refresh_token: str) -> None:
        token = await self.refresh_token_repository.get_by_token(refresh_token)
        if token is None or token.user_id != user_id:
            # refresh_token 자체가 없거나(이미 무효화 포함) 본인 소유가 아니면
            # Access Token 검증 실패와 동일하게 취급해 존재 여부를 노출하지 않는다.
            raise InvalidTokenError()

        await self.refresh_token_repository.revoke(token)
        await self.session.commit()

    async def refresh(self, refresh_token: str) -> AuthTokens:
        """RTR(Refresh Token Rotation) 방식으로 Access/Refresh Token을 재발급한다."""

        try:
            payload = decode_token(refresh_token)
        except jwt.PyJWTError as exc:
            raise InvalidRefreshTokenError() from exc

        if payload.get("type") != "refresh":
            raise InvalidRefreshTokenError()

        token = await self.refresh_token_repository.get_by_token_any_status(refresh_token)
        if token is None:
            raise InvalidRefreshTokenError()

        if token.is_revoked:
            # 이미 회전(rotate)되어 폐기된 Refresh Token의 재사용 시도 → 탈취 의심,
            # 해당 사용자의 모든 Refresh Token을 전면 무효화해 재로그인을 강제한다.
            await self.refresh_token_repository.revoke_all_by_user(token.user_id)
            await self.session.commit()
            raise InvalidRefreshTokenError()

        user = await self.user_repository.get_by_id(token.user_id)
        if user is None:
            raise InvalidRefreshTokenError()

        await self.refresh_token_repository.revoke(token)
        return await self._issue_tokens(user)

    async def get_me(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            # 토큰 발급 이후 탈퇴(soft delete)된 사용자 등 → 인증 실패로 취급한다.
            raise InvalidTokenError()

        return user

    async def leave(self, user_id: int) -> None:
        """회원 탈퇴: soft delete와 함께 개인정보를 비식별화(마스킹)하고, 발급된 토큰을 모두 무효화한다."""

        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        user.email = None
        user.name = None
        user.phone = None
        user.password_hash = None
        user.social_provider = None
        user.social_id = None

        await self.user_repository.soft_delete(user)
        await self.refresh_token_repository.revoke_all_by_user(user_id)
        await self.session.commit()

    async def signup(self, payload: SignupRequest) -> User:
        if payload.role == "TEACHER":
            self._validate_teacher_signup_code(payload.signup_code)

        await self._ensure_email_not_taken(payload.email)

        user = User(
            email=payload.email,
            password_hash=hash_password(payload.password),
            name=payload.name,
            phone=payload.phone,
            role=payload.role,
            class_id=payload.class_id,
        )
        user = await self.user_repository.create(user)
        await self.session.commit()
        return user

    def _validate_teacher_signup_code(self, signup_code: str | None) -> None:
        if not signup_code or signup_code != settings.TEACHER_SIGNUP_CODE:
            raise InvalidSignupCodeError()

    async def _ensure_email_not_taken(self, email: str) -> None:
        existing_user = await self.user_repository.get_by_email(email)
        if existing_user is not None:
            raise EmailAlreadyExistsError()
