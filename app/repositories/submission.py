from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.submission import Submission
from app.repositories.base import BaseRepository


class SubmissionRepository(BaseRepository[Submission]):
    model = Submission

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_final_by_user_and_assignment(
        self,
        user_id: int,
        assignment_id: int,
    ) -> Submission | None:
        stmt = select(Submission).where(
            Submission.user_id == user_id,
            Submission.assignment_id == assignment_id,
            Submission.is_final.is_(True),
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_assignment(self, assignment_id: int) -> list[Submission]:
        stmt = (
            select(Submission)
            .where(Submission.assignment_id == assignment_id)
            .order_by(Submission.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_user(self, user_id: int) -> list[Submission]:
        stmt = (
            select(Submission)
            .where(Submission.user_id == user_id)
            .order_by(Submission.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def mark_as_final(self, submission: Submission) -> Submission:
        submission.is_final = True
        return await self.update(submission)
