"""회원가입 관련 비즈니스 로직."""

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import EmailAlreadyExistsError, InvalidSignupCodeError
from app.core.security import hash_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.auth import SignupRequest


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)

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
