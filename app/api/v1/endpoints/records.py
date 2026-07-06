from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.dashboard import ErrorDetail
from app.schemas.records import StudentRecordsResponse
from app.services.record_service import RecordService

router = APIRouter()


@router.get(
    "/student/records",
    summary="단계별 최종 성적/피드백 조회",
    status_code=status.HTTP_200_OK,
    response_model=StudentRecordsResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "권한 불일치 (교사 ↔ 학생 API 교차 호출)"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_student_records(
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StudentRecordsResponse:
    return await RecordService(db).get_student_records(user_id)


@router.get("/teacher/records/grades", summary="학급 성적 관리 조회")
def get_teacher_grades():
    return {"status": "success", "data": {}}


@router.get("/teacher/records/students", summary="학급 전체 학생 현황 조회")
def get_teacher_students():
    return {"status": "success", "data": {}}
