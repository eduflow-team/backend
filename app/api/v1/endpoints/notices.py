from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.dashboard import ErrorDetail
from app.schemas.notices import (
    StudentNoticeListResponse,
    TeacherNoticeCreateRequest,
    TeacherNoticeCreateResponse,
)
from app.services.notice_service import NoticeService

router = APIRouter()


@router.get(
    "/student/notices",
    summary="전체 공지사항 목록",
    status_code=status.HTTP_200_OK,
    response_model=StudentNoticeListResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "role 불일치"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_student_notices(
    page: int = Query(1, ge=1, description="페이지 번호"),
    size: int = Query(10, ge=1, le=100, description="페이지당 개수"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> StudentNoticeListResponse:
    return await NoticeService(db).get_student_notices(user_id, page=page, size=size)


@router.post(
    "/teacher/notices",
    summary="새 공지사항 작성",
    status_code=status.HTTP_201_CREATED,
    response_model=TeacherNoticeCreateResponse,
    responses={
        400: {"model": ErrorDetail, "description": "제목 또는 내용 누락"},
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "role ≠ TEACHER"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def create_teacher_notice(
    payload: TeacherNoticeCreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> TeacherNoticeCreateResponse:
    return await NoticeService(db).create_teacher_notice(user_id, payload)


@router.delete("/teacher/notices/{id}", summary="공지사항 삭제")
def delete_teacher_notice(id: int):
    return {"status": "success", "data": {}}
