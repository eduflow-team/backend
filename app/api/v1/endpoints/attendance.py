from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.attendance import ErrorDetail, StudentAttendanceResponse
from app.services.attendance_service import AttendanceService

router = APIRouter()


@router.get(
    "/student/attendance",
    summary="개인 누적 출석 기록",
    status_code=status.HTTP_200_OK,
    response_model=StudentAttendanceResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "권한 불일치 (교사 ↔ 학생 API 교차 호출)"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_student_attendance(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StudentAttendanceResponse:
    return await AttendanceService(db).get_student_attendance(user_id)


@router.get("/teacher/attendance", summary="학급 출석부 명단 조회")
def get_teacher_attendance():
    return {"status": "success", "data": {}}


@router.patch("/teacher/attendance", summary="학급 출석부 수정 및 저장")
def update_teacher_attendance():
    return {"status": "success", "data": {}}
