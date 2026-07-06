"""성적·기록(records) 도메인 비즈니스 로직."""

from collections import defaultdict

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import InvalidTokenError, RecordsAccessForbiddenError
from app.models.assignment import Assignment
from app.models.enums import ProgressStatus
from app.models.evaluation import Evaluation
from app.models.student_status import StudentAssignmentStatus
from app.models.submission import Submission
from app.models.user import User
from app.repositories.assignment import AssignmentRepository
from app.repositories.class_ import ClassRepository
from app.repositories.evaluation import EvaluationRepository
from app.repositories.student_status import StudentAssignmentStatusRepository
from app.repositories.submission import SubmissionRepository
from app.repositories.user import UserRepository
from app.schemas.records import (
    StudentRecordItem,
    StudentRecordsResponse,
    TeacherGradesStudentItem,
    TeacherRecordsGradesResponse,
    TeacherRecordsStudentItem,
    TeacherRecordsStudentsResponse,
    TeacherStageAverages,
    TeacherStageDetailItem,
    TeacherStageDetails,
    TeacherStageSummary,
    TeacherStageSummaryItem,
)

_TOTAL_STAGE_COUNT = 4
_KNOWN_PROGRESS_STATUSES = {s.value for s in ProgressStatus}


class RecordService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.user_repository = UserRepository(session)
        self.class_repository = ClassRepository(session)
        self.assignment_repository = AssignmentRepository(session)
        self.student_status_repository = StudentAssignmentStatusRepository(session)
        self.submission_repository = SubmissionRepository(session)
        self.evaluation_repository = EvaluationRepository(session)

    async def get_student_records(self, user_id: int) -> StudentRecordsResponse:
        user = await self._get_authorized_student(user_id)

        latest_assignment_by_stage = await self._get_latest_assignment_by_stage(user.class_id)
        statuses = await self.student_status_repository.list_by_user(user_id)
        status_by_assignment_id = {status.assignment_id: status for status in statuses}

        submissions = await self.submission_repository.list_by_user(user_id)
        submission_counts = self._count_submissions_by_assignment(submissions)
        final_submission_by_assignment = self._index_final_submissions(submissions)

        evaluations = await self.evaluation_repository.list_by_user(user_id)
        evaluation_by_submission_id = {
            evaluation.submission_id: evaluation for evaluation in evaluations
        }

        records = [
            self._build_student_record_item(
                stage,
                latest_assignment_by_stage.get(stage),
                status_by_assignment_id,
                submission_counts,
                final_submission_by_assignment,
                evaluation_by_submission_id,
            )
            for stage in range(1, _TOTAL_STAGE_COUNT + 1)
        ]

        class_total_average = await self._compute_class_total_average(user.class_id)

        return StudentRecordsResponse(
            class_total_average=class_total_average,
            records=records,
        )

    async def get_teacher_records_students(
        self, user_id: int
    ) -> TeacherRecordsStudentsResponse:
        teacher = await self._get_authorized_teacher(user_id)
        class_ids = await self._get_teacher_class_ids(teacher)

        students = await self.user_repository.list_by_class_ids(class_ids, role="STUDENT")
        if not students:
            return TeacherRecordsStudentsResponse(students=[])

        latest_assignment_by_class = await self._load_latest_assignment_by_class(class_ids)
        assignment_ids = [
            assignment.assignment_id
            for assignments in latest_assignment_by_class.values()
            for assignment in assignments.values()
        ]
        statuses = await self.student_status_repository.list_by_assignment_ids(assignment_ids)
        statuses_by_student = self._group_statuses_by_student(statuses)

        items = [
            self._build_teacher_records_student_item(
                student,
                latest_assignment_by_class.get(student.class_id or -1, {}),
                statuses_by_student.get(student.user_id, {}),
            )
            for student in students
        ]
        return TeacherRecordsStudentsResponse(students=items)

    async def get_teacher_records_grades(
        self, user_id: int
    ) -> TeacherRecordsGradesResponse:
        teacher = await self._get_authorized_teacher(user_id)
        class_ids = await self._get_teacher_class_ids(teacher)

        students = await self.user_repository.list_by_class_ids(class_ids, role="STUDENT")
        latest_assignment_by_class = await self._load_latest_assignment_by_class(class_ids)
        assignment_ids = [
            assignment.assignment_id
            for assignments in latest_assignment_by_class.values()
            for assignment in assignments.values()
        ]

        statuses = await self.student_status_repository.list_by_assignment_ids(assignment_ids)
        statuses_by_student = self._group_statuses_by_student(statuses)
        evaluations_by_user_assignment = await self._load_evaluations_by_user_assignment(
            assignment_ids
        )

        stage_scores_by_stage: dict[int, list[int]] = defaultdict(list)
        student_items: list[TeacherGradesStudentItem] = []

        for student in students:
            latest_assignment_by_stage = latest_assignment_by_class.get(
                student.class_id or -1, {}
            )
            status_by_assignment_id = statuses_by_student.get(student.user_id, {})
            student_items.append(
                self._build_teacher_grades_student_item(
                    student,
                    latest_assignment_by_stage,
                    status_by_assignment_id,
                    evaluations_by_user_assignment,
                    stage_scores_by_stage,
                )
            )

        stage_averages = self._build_stage_averages(stage_scores_by_stage)

        return TeacherRecordsGradesResponse(
            stage_averages=stage_averages,
            students=student_items,
        )

    async def _get_authorized_student(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "STUDENT":
            raise RecordsAccessForbiddenError()

        return user

    async def _get_authorized_teacher(self, user_id: int) -> User:
        user = await self.user_repository.get_by_id(user_id)
        if user is None:
            raise InvalidTokenError()

        if user.role != "TEACHER":
            raise RecordsAccessForbiddenError()

        return user

    async def _get_teacher_class_ids(self, teacher: User) -> list[int]:
        classes = await self.class_repository.list_by_teacher(teacher.user_id)
        class_ids = {c.class_id for c in classes}
        if teacher.class_id is not None:
            class_ids.add(teacher.class_id)
        return sorted(class_ids)

    async def _load_latest_assignment_by_class(
        self, class_ids: list[int]
    ) -> dict[int, dict[int, Assignment]]:
        latest_by_class: dict[int, dict[int, Assignment]] = {}
        for class_id in class_ids:
            assignments = await self.assignment_repository.list_by_class(class_id)
            latest_by_class[class_id] = self._group_latest_by_stage(assignments)
        return latest_by_class

    async def _get_latest_assignment_by_stage(
        self, class_id: int | None
    ) -> dict[int, Assignment]:
        if class_id is None:
            return {}

        assignments = await self.assignment_repository.list_by_class(class_id)
        return self._group_latest_by_stage(assignments)

    async def _compute_class_total_average(self, class_id: int | None) -> float:
        if class_id is None:
            return 0.0

        students = await self.user_repository.list_by_class_ids([class_id], role="STUDENT")
        if not students:
            return 0.0

        assignments = await self.assignment_repository.list_by_class(class_id)
        assignment_ids = [assignment.assignment_id for assignment in assignments]
        if not assignment_ids:
            return 0.0

        statuses = await self.student_status_repository.list_by_assignment_ids(assignment_ids)
        statuses_by_student = self._group_statuses_by_student(statuses)

        total_scores = [
            self._get_total_score(statuses_by_student.get(student.user_id, {}))
            for student in students
        ]
        return round(sum(total_scores) / len(students), 2)

    def _build_student_record_item(
        self,
        stage: int,
        assignment: Assignment | None,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
        submission_counts: dict[int, int],
        final_submission_by_assignment: dict[int, Submission],
        evaluation_by_submission_id: dict[int, Evaluation],
    ) -> StudentRecordItem:
        status_row = (
            status_by_assignment_id.get(assignment.assignment_id) if assignment else None
        )
        progress_status = self._resolve_progress_status(status_row)
        is_completed = progress_status == ProgressStatus.COMPLETED.value

        attempts_count = (
            submission_counts.get(assignment.assignment_id, 0) if assignment else 0
        )

        highest_score = status_row.best_score if is_completed and status_row else None
        ai_feedback: str | None = None
        metadata = None

        if is_completed and assignment is not None:
            final_submission = final_submission_by_assignment.get(assignment.assignment_id)
            if final_submission is not None:
                evaluation = evaluation_by_submission_id.get(final_submission.submission_id)
                if evaluation is not None:
                    ai_feedback = evaluation.feedback
                    metadata = evaluation.evaluation_metadata

        return StudentRecordItem(
            stage=stage,
            title=assignment.title if assignment else None,
            highest_score=highest_score,
            attempts_count=attempts_count,
            ai_feedback=ai_feedback,
            metadata=metadata,
        )

    def _build_teacher_records_student_item(
        self,
        student: User,
        latest_assignment_by_stage: dict[int, Assignment],
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
    ) -> TeacherRecordsStudentItem:
        stage_items = {
            f"stage_{stage}": self._build_teacher_stage_summary_item(
                latest_assignment_by_stage.get(stage),
                status_by_assignment_id,
            )
            for stage in range(1, _TOTAL_STAGE_COUNT + 1)
        }

        return TeacherRecordsStudentItem(
            student_id=student.user_id,
            student_name=student.name or "",
            stage_summary=TeacherStageSummary(**stage_items),
        )

    def _build_teacher_stage_summary_item(
        self,
        assignment: Assignment | None,
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
    ) -> TeacherStageSummaryItem:
        status_row = (
            status_by_assignment_id.get(assignment.assignment_id) if assignment else None
        )
        progress_status = self._resolve_progress_status(status_row)
        score = (
            status_row.best_score
            if progress_status == ProgressStatus.COMPLETED.value and status_row
            else None
        )

        return TeacherStageSummaryItem(
            status=ProgressStatus(progress_status),
            score=score,
        )

    def _build_teacher_grades_student_item(
        self,
        student: User,
        latest_assignment_by_stage: dict[int, Assignment],
        status_by_assignment_id: dict[int, StudentAssignmentStatus],
        evaluations_by_user_assignment: dict[tuple[int, int], Evaluation],
        stage_scores_by_stage: dict[int, list[int]],
    ) -> TeacherGradesStudentItem:
        stage_items: dict[str, TeacherStageDetailItem] = {}
        completed_scores: list[int] = []

        for stage in range(1, _TOTAL_STAGE_COUNT + 1):
            assignment = latest_assignment_by_stage.get(stage)
            status_row = (
                status_by_assignment_id.get(assignment.assignment_id) if assignment else None
            )
            progress_status = self._resolve_progress_status(status_row)
            score: int | None = None
            summary: str | None = None

            if (
                progress_status == ProgressStatus.COMPLETED.value
                and status_row is not None
                and status_row.best_score is not None
            ):
                score = status_row.best_score
                completed_scores.append(score)
                stage_scores_by_stage[stage].append(score)

                if assignment is not None:
                    evaluation = evaluations_by_user_assignment.get(
                        (student.user_id, assignment.assignment_id)
                    )
                    if evaluation is not None:
                        summary = self._build_stage_detail_summary(
                            evaluation.evaluation_metadata
                        )

            stage_items[f"stage_{stage}"] = TeacherStageDetailItem(
                score=score,
                summary=summary,
            )

        average_score = (
            round(sum(completed_scores) / len(completed_scores), 1)
            if completed_scores
            else 0.0
        )

        return TeacherGradesStudentItem(
            student_id=student.user_id,
            student_name=student.name or "",
            average_score=average_score,
            stage_details=TeacherStageDetails(**stage_items),
        )

    def _build_stage_averages(
        self, stage_scores_by_stage: dict[int, list[int]]
    ) -> TeacherStageAverages:
        stage_average_values: dict[str, float | None] = {}
        non_null_averages: list[float] = []

        for stage in range(1, _TOTAL_STAGE_COUNT + 1):
            scores = stage_scores_by_stage.get(stage, [])
            if scores:
                average = round(sum(scores) / len(scores), 1)
                stage_average_values[f"stage_{stage}"] = average
                non_null_averages.append(average)
            else:
                stage_average_values[f"stage_{stage}"] = None

        total_average = (
            round(sum(non_null_averages) / len(non_null_averages), 1)
            if non_null_averages
            else 0.0
        )

        return TeacherStageAverages(
            **stage_average_values,
            total_average=total_average,
        )

    def _build_stage_detail_summary(self, metadata: dict | None) -> str | None:
        if not metadata:
            return None

        if summary := metadata.get("summary"):
            return str(summary)

        if optimal_parameters := metadata.get("optimal_parameters"):
            return str(optimal_parameters)

        found_errors = metadata.get("found_errors")
        if isinstance(found_errors, list) and found_errors:
            return f"{len(found_errors)}/{len(found_errors)} ✅"

        return None

    async def _load_evaluations_by_user_assignment(
        self, assignment_ids: list[int]
    ) -> dict[tuple[int, int], Evaluation]:
        mapping: dict[tuple[int, int], Evaluation] = {}
        for assignment_id in assignment_ids:
            submissions = await self.submission_repository.list_by_assignment(assignment_id)
            for submission in submissions:
                if not submission.is_final:
                    continue

                evaluation = await self.evaluation_repository.get_by_submission_id(
                    submission.submission_id
                )
                if evaluation is not None:
                    mapping[(submission.user_id, assignment_id)] = evaluation

        return mapping

    def _group_latest_by_stage(self, assignments: list[Assignment]) -> dict[int, Assignment]:
        latest_by_stage: dict[int, Assignment] = {}
        for assignment in assignments:
            if assignment.stage is None or assignment.stage in latest_by_stage:
                continue
            latest_by_stage[assignment.stage] = assignment
        return latest_by_stage

    def _group_statuses_by_student(
        self, statuses: list[StudentAssignmentStatus]
    ) -> dict[int, dict[int, StudentAssignmentStatus]]:
        by_student: dict[int, dict[int, StudentAssignmentStatus]] = defaultdict(dict)
        for status_row in statuses:
            by_student[status_row.user_id][status_row.assignment_id] = status_row
        return by_student

    def _count_submissions_by_assignment(
        self, submissions: list[Submission]
    ) -> dict[int, int]:
        counts: dict[int, int] = defaultdict(int)
        for submission in submissions:
            counts[submission.assignment_id] += 1
        return counts

    def _index_final_submissions(
        self, submissions: list[Submission]
    ) -> dict[int, Submission]:
        finals: dict[int, Submission] = {}
        for submission in submissions:
            if submission.is_final and submission.assignment_id not in finals:
                finals[submission.assignment_id] = submission
        return finals

    def _get_total_score(self, status_by_assignment_id: dict[int, StudentAssignmentStatus]) -> int:
        return sum(
            status.total_literacy_score
            for status in status_by_assignment_id.values()
            if status.total_literacy_score is not None
        )

    def _resolve_progress_status(self, status_row: StudentAssignmentStatus | None) -> str:
        if status_row is None:
            return ProgressStatus.NOT_STARTED.value

        progress_status = (status_row.progress_status or ProgressStatus.NOT_STARTED.value).upper()
        if progress_status not in _KNOWN_PROGRESS_STATUSES:
            return ProgressStatus.NOT_STARTED.value

        return progress_status
