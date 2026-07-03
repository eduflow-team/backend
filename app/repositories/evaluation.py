from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.assignment import Assignment
from app.models.evaluation import Evaluation
from app.models.submission import Submission
from app.repositories.base import BaseRepository


class EvaluationRepository(BaseRepository[Evaluation]):
    model = Evaluation

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_submission_id(self, submission_id: int) -> Evaluation | None:
        stmt = select(Evaluation).where(Evaluation.submission_id == submission_id)
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: int) -> list[Evaluation]:
        stmt = (
            select(Evaluation)
            .join(Submission, Evaluation.submission_id == Submission.submission_id)
            .where(Submission.user_id == user_id)
            .order_by(Evaluation.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_class(self, class_id: int) -> list[Evaluation]:
        stmt = (
            select(Evaluation)
            .join(Submission, Evaluation.submission_id == Submission.submission_id)
            .join(Assignment, Submission.assignment_id == Assignment.assignment_id)
            .where(Assignment.class_id == class_id)
            .order_by(Evaluation.created_at.desc())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
