from app.db.base import Base
from app.models.assignment import Assignment
from app.models.attendance import AttendanceRecord
from app.models.class_ import Class
from app.models.document import Document, DocumentChunk
from app.models.evaluation import Evaluation
from app.models.notice import Notice
from app.models.stage import (
    Stage1AssignmentDetail,
    Stage2AssignmentDetail,
    Stage2ErrorAnswer,
)
from app.models.student_status import StudentAssignmentStatus
from app.models.submission import (
    Stage1Attempt,
    Stage2CorrectionSubmission,
    Stage2HighlightSubmission,
    Submission,
)
from app.models.user import RefreshToken, User

__all__ = [
    "Base",
    "Assignment",
    "AttendanceRecord",
    "Class",
    "Document",
    "DocumentChunk",
    "Evaluation",
    "Notice",
    "RefreshToken",
    "Stage1AssignmentDetail",
    "Stage1Attempt",
    "Stage2AssignmentDetail",
    "Stage2CorrectionSubmission",
    "Stage2ErrorAnswer",
    "Stage2HighlightSubmission",
    "StudentAssignmentStatus",
    "Submission",
    "User",
]
