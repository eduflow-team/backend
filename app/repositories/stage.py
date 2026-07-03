from sqlalchemy import select

from app.models.stage import (
    Stage1AssignmentDetail,
    Stage2AssignmentDetail,
    Stage2ErrorAnswer,
)
from app.models.submission import (
    Stage1Attempt,
    Stage2CorrectionSubmission,
    Stage2HighlightSubmission,
)
from app.repositories.base import BaseRepository


class Stage1DetailRepository(BaseRepository[Stage1AssignmentDetail]):
    model = Stage1AssignmentDetail

    async def get_by_assignment_id(self, assignment_id: int) -> Stage1AssignmentDetail | None:
        stmt = select(Stage1AssignmentDetail).where(
            Stage1AssignmentDetail.assignment_id == assignment_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class Stage2DetailRepository(BaseRepository[Stage2AssignmentDetail]):
    model = Stage2AssignmentDetail

    async def get_by_assignment_id(self, assignment_id: int) -> Stage2AssignmentDetail | None:
        stmt = select(Stage2AssignmentDetail).where(
            Stage2AssignmentDetail.assignment_id == assignment_id
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()


class Stage2ErrorAnswerRepository(BaseRepository[Stage2ErrorAnswer]):
    model = Stage2ErrorAnswer

    async def list_by_assignment_id(self, assignment_id: int) -> list[Stage2ErrorAnswer]:
        stmt = (
            select(Stage2ErrorAnswer)
            .where(Stage2ErrorAnswer.assignment_id == assignment_id)
            .order_by(Stage2ErrorAnswer.answer_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class Stage1AttemptRepository(BaseRepository[Stage1Attempt]):
    model = Stage1Attempt

    async def list_by_user_and_assignment(
        self,
        user_id: int,
        assignment_id: int,
    ) -> list[Stage1Attempt]:
        stmt = (
            select(Stage1Attempt)
            .where(
                Stage1Attempt.user_id == user_id,
                Stage1Attempt.assignment_id == assignment_id,
            )
            .order_by(Stage1Attempt.attempt_number)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class Stage2HighlightRepository(BaseRepository[Stage2HighlightSubmission]):
    model = Stage2HighlightSubmission

    async def list_by_user_and_assignment(
        self,
        user_id: int,
        assignment_id: int,
    ) -> list[Stage2HighlightSubmission]:
        stmt = (
            select(Stage2HighlightSubmission)
            .where(
                Stage2HighlightSubmission.user_id == user_id,
                Stage2HighlightSubmission.assignment_id == assignment_id,
            )
            .order_by(Stage2HighlightSubmission.highlight_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())


class Stage2CorrectionRepository(BaseRepository[Stage2CorrectionSubmission]):
    model = Stage2CorrectionSubmission

    async def list_by_user_and_assignment(
        self,
        user_id: int,
        assignment_id: int,
    ) -> list[Stage2CorrectionSubmission]:
        stmt = (
            select(Stage2CorrectionSubmission)
            .where(
                Stage2CorrectionSubmission.user_id == user_id,
                Stage2CorrectionSubmission.assignment_id == assignment_id,
            )
            .order_by(Stage2CorrectionSubmission.correction_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
