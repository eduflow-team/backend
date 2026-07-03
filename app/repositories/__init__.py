from collections.abc import Callable
from typing import TypeVar

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.repositories.assignment import AssignmentRepository
from app.repositories.attendance import AttendanceRepository
from app.repositories.base import BaseRepository
from app.repositories.chunk import DocumentChunkRepository
from app.repositories.class_ import ClassRepository
from app.repositories.document import DocumentRepository
from app.repositories.evaluation import EvaluationRepository
from app.repositories.notice import NoticeRepository
from app.repositories.stage import (
    Stage1AttemptRepository,
    Stage1DetailRepository,
    Stage2CorrectionRepository,
    Stage2DetailRepository,
    Stage2ErrorAnswerRepository,
    Stage2HighlightRepository,
)
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.submission import SubmissionRepository
from app.repositories.user import RefreshTokenRepository, UserRepository

RepoT = TypeVar("RepoT", bound=BaseRepository)


def _repo_factory(repo_cls: type[RepoT]) -> Callable[[AsyncSession], RepoT]:
    def _get_repo(session: AsyncSession = Depends(get_db)) -> RepoT:
        return repo_cls(session)

    return _get_repo


get_user_repository = _repo_factory(UserRepository)
get_refresh_token_repository = _repo_factory(RefreshTokenRepository)
get_class_repository = _repo_factory(ClassRepository)
get_document_repository = _repo_factory(DocumentRepository)
get_document_chunk_repository = _repo_factory(DocumentChunkRepository)
get_assignment_repository = _repo_factory(AssignmentRepository)
get_submission_repository = _repo_factory(SubmissionRepository)
get_evaluation_repository = _repo_factory(EvaluationRepository)
get_student_status_repository = _repo_factory(StudentAssignmentStatusRepository)
get_stage1_detail_repository = _repo_factory(Stage1DetailRepository)
get_stage2_detail_repository = _repo_factory(Stage2DetailRepository)
get_stage2_error_answer_repository = _repo_factory(Stage2ErrorAnswerRepository)
get_stage1_attempt_repository = _repo_factory(Stage1AttemptRepository)
get_stage2_highlight_repository = _repo_factory(Stage2HighlightRepository)
get_stage2_correction_repository = _repo_factory(Stage2CorrectionRepository)
get_notice_repository = _repo_factory(NoticeRepository)
get_attendance_repository = _repo_factory(AttendanceRepository)

__all__ = [
    "AssignmentRepository",
    "AttendanceRepository",
    "BaseRepository",
    "ClassRepository",
    "DocumentChunkRepository",
    "DocumentRepository",
    "EvaluationRepository",
    "NoticeRepository",
    "RefreshTokenRepository",
    "Stage1AttemptRepository",
    "Stage1DetailRepository",
    "Stage2CorrectionRepository",
    "Stage2DetailRepository",
    "Stage2ErrorAnswerRepository",
    "Stage2HighlightRepository",
    "StudentAssignmentStatusRepository",
    "SubmissionRepository",
    "UserRepository",
    "get_assignment_repository",
    "get_attendance_repository",
    "get_class_repository",
    "get_document_chunk_repository",
    "get_document_repository",
    "get_evaluation_repository",
    "get_notice_repository",
    "get_refresh_token_repository",
    "get_stage1_attempt_repository",
    "get_stage1_detail_repository",
    "get_stage2_correction_repository",
    "get_stage2_detail_repository",
    "get_stage2_error_answer_repository",
    "get_stage2_highlight_repository",
    "get_student_status_repository",
    "get_submission_repository",
    "get_user_repository",
]
