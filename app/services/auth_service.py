"""회원가입 / 로그인 관련 비즈니스 로직."""

from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    EmailAlreadyExistsError,
    InvalidCredentialsError,
    InvalidSignupCodeError,
)
from app.core.security import (
    create_access_token,
    create_refresh_token,
    hash_password,
    verify_password,
)
from app.models.user import RefreshToken, User
from app.repositories.user import RefreshTokenRepository, UserRepository
from app.schemas.auth import LoginRequest, SignupRequest


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
