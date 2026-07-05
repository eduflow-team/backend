from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.enums import ProgressStatus
from app.models.student_status import StudentAssignmentStatus
from app.repositories.base import BaseRepository


class StudentAssignmentStatusRepository(BaseRepository[StudentAssignmentStatus]):
    model = StudentAssignmentStatus

    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session)

    async def get_by_user_and_assignment(
        self,
        user_id: int,
        assignment_id: int,
    ) -> StudentAssignmentStatus | None:
        stmt = select(StudentAssignmentStatus).where(
            StudentAssignmentStatus.user_id == user_id,
            StudentAssignmentStatus.assignment_id == assignment_id,
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def get_or_create(
        self,
        user_id: int,
        assignment_id: int,
        *,
        progress_status: str | None = ProgressStatus.NOT_STARTED.value,
        remaining_attempts: int | None = None,
    ) -> StudentAssignmentStatus:
        status = await self.get_by_user_and_assignment(user_id, assignment_id)
        if status is not None:
            return status

        status = StudentAssignmentStatus(
            user_id=user_id,
            assignment_id=assignment_id,
            progress_status=progress_status,
            remaining_attempts=remaining_attempts,
        )
        return await self.create(status)

    async def update_progress(
        self,
        status: StudentAssignmentStatus,
        **fields: object,
    ) -> StudentAssignmentStatus:
        for key, value in fields.items():
            if hasattr(status, key) and value is not None:
                setattr(status, key, value)
        status.last_accessed_at = datetime.now(UTC)
        return await self.update(status)

    async def list_by_user(self, user_id: int) -> list[StudentAssignmentStatus]:
        stmt = (
            select(StudentAssignmentStatus)
            .where(StudentAssignmentStatus.user_id == user_id)
            .order_by(StudentAssignmentStatus.updated_at.desc().nulls_last())
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def list_by_assignment(self, assignment_id: int) -> list[StudentAssignmentStatus]:
        stmt = (
            select(StudentAssignmentStatus)
            .where(StudentAssignmentStatus.assignment_id == assignment_id)
            .order_by(StudentAssignmentStatus.user_id)
        )
        result = await self.session.execute(stmt)
        return list(result.scalars().all())
