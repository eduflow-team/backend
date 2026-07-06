from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.dashboard import (
    ErrorDetail,
    StudentAssignmentListResponse,
    StudentDashboardSummaryResponse,
    TeacherAssignmentListResponse,
    TeacherDashboardSummaryResponse,
    TeacherUnsubmittedStudentsResponse,
)
from app.services.dashboard_service import DashboardService

router = APIRouter()


@router.get(
    "/student/dashboard/summary",
    summary="학생 대시보드 요약",
    status_code=status.HTTP_200_OK,
    response_model=StudentDashboardSummaryResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "학생 권한으로 교사 API를 호출하거나 그 반대의 경우"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_student_dashboard_summary(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StudentDashboardSummaryResponse:
    return await DashboardService(db).get_student_summary(user_id)


@router.get(
    "/student/dashboard/assignments",
    summary="과제 목록 조회",
    status_code=status.HTTP_200_OK,
    response_model=StudentAssignmentListResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "학생 권한으로 교사 API를 호출하거나 그 반대의 경우"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_student_dashboard_assignments(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StudentAssignmentListResponse:
    return await DashboardService(db).get_student_assignments(user_id)


@router.get(
    "/teacher/dashboard/summary",
    summary="교사 대시보드 통계",
    status_code=status.HTTP_200_OK,
    response_model=TeacherDashboardSummaryResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "학생 권한으로 교사 API를 호출하거나 그 반대의 경우"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_teacher_dashboard_summary(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TeacherDashboardSummaryResponse:
    return await DashboardService(db).get_teacher_summary(user_id)


@router.get(
    "/teacher/dashboard/students/unsubmitted",
    summary="미제출 학생 목록",
    status_code=status.HTTP_200_OK,
    response_model=TeacherUnsubmittedStudentsResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "학생 권한으로 교사 API를 호출하거나 그 반대의 경우"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_unsubmitted_students(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TeacherUnsubmittedStudentsResponse:
    return await DashboardService(db).get_unsubmitted_students(user_id)


@router.get(
    "/teacher/dashboard/assignments",
    summary="생성 과제 목록",
    status_code=status.HTTP_200_OK,
    response_model=TeacherAssignmentListResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "학생 계정으로 교사용 과제 목록 조회 시도"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_teacher_dashboard_assignments(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TeacherAssignmentListResponse:
    return await DashboardService(db).get_teacher_assignments(user_id)


@router.delete("/teacher/dashboard/assignments/{id}", summary="과제 삭제")
def delete_teacher_assignment(id: int):
    return {"status": "success", "data": {}}
