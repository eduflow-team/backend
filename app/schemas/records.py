"""성적·기록(records) API의 Pydantic 스키마."""

from typing import Any

from pydantic import BaseModel

from app.models.enums import ProgressStatus


class StudentRecordItem(BaseModel):
    """GET /student/records 응답의 단계별 기록 항목."""

    stage: int
    title: str | None
    highest_score: int | None
    attempts_count: int
    ai_feedback: str | None
    metadata: dict[str, Any] | None


class StudentRecordsResponse(BaseModel):
    """GET /student/records 성공 응답."""

    class_total_average: float
    records: list[StudentRecordItem]


class TeacherStageSummaryItem(BaseModel):
    """GET /teacher/records/students의 단계별 제출 상태 항목."""

    status: ProgressStatus
    score: int | None


class TeacherStageSummary(BaseModel):
    """단계별 제출 상태 맵 (`stage_1` ~ `stage_4`)."""

    stage_1: TeacherStageSummaryItem
    stage_2: TeacherStageSummaryItem
    stage_3: TeacherStageSummaryItem
    stage_4: TeacherStageSummaryItem


class TeacherRecordsStudentItem(BaseModel):
    """GET /teacher/records/students의 학생 항목."""

    student_id: int
    student_name: str
    stage_summary: TeacherStageSummary


class TeacherRecordsStudentsResponse(BaseModel):
    """GET /teacher/records/students 성공 응답."""

    students: list[TeacherRecordsStudentItem]


class TeacherStageDetailItem(BaseModel):
    """GET /teacher/records/grades의 단계별 성적 상세 항목."""

    score: int | None
    summary: str | None


class TeacherStageDetails(BaseModel):
    """단계별 성적 상세 맵 (`stage_1` ~ `stage_4`)."""

    stage_1: TeacherStageDetailItem
    stage_2: TeacherStageDetailItem
    stage_3: TeacherStageDetailItem
    stage_4: TeacherStageDetailItem


class TeacherStageAverages(BaseModel):
    """학급 단계별 평균 점수."""

    stage_1: float | None
    stage_2: float | None
    stage_3: float | None
    stage_4: float | None
    total_average: float


class TeacherGradesStudentItem(BaseModel):
    """GET /teacher/records/grades의 학생 항목."""

    student_id: int
    student_name: str
    average_score: float
    stage_details: TeacherStageDetails


class TeacherRecordsGradesResponse(BaseModel):
    """GET /teacher/records/grades 성공 응답."""

    stage_averages: TeacherStageAverages
    students: list[TeacherGradesStudentItem]
