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
