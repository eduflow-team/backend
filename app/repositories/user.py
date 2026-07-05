from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import RefreshToken, User
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_email(self, email: str) -> User | None:
        stmt = select(User).where(User.email == email)
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_social_id(self, social_provider: str, social_id: str) -> User | None:
        stmt = select(User).where(
            User.social_provider == social_provider,
            User.social_id == social_id,
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_class_id(self, class_id: int) -> list[User]:
        stmt = (
            select(User)
            .where(User.class_id == class_id)
            .order_by(User.user_id)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def search_by_name(self, keyword: str, *, limit: int = 20) -> list[User]:
        stmt = (
            select(User)
            .where(User.name.ilike(f"%{keyword}%"))
            .order_by(User.name)
            .limit(limit)
        )
        stmt = self._apply_not_deleted(stmt)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    model = RefreshToken

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_token(self, refresh_token: str) -> RefreshToken | None:
        stmt = select(RefreshToken).where(
            RefreshToken.refresh_token == refresh_token,
            RefreshToken.is_revoked.is_(False),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_by_token_any_status(self, refresh_token: str) -> RefreshToken | None:
        """무효화 여부와 상관없이 토큰을 조회한다.

        RTR(Refresh Token Rotation) 재사용 탐지를 위해, 이미 `revoke`된 토큰인지도
        구분해야 하는 `/auth/refresh`에서만 사용한다.
        """

        stmt = select(RefreshToken).where(RefreshToken.refresh_token == refresh_token)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def revoke(self, token: RefreshToken) -> RefreshToken:
        token.is_revoked = True
        return await self.update(token)

    async def revoke_all_by_user(self, user_id: int) -> None:
        stmt = (
            update(RefreshToken)
            .where(
                RefreshToken.user_id == user_id,
                RefreshToken.is_revoked.is_(False),
            )
            .values(is_revoked=True)
        )
        await self.session.execute(stmt)
        await self.session.flush()
