from fastapi import APIRouter, Depends, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.dashboard import ErrorDetail
from app.schemas.search import SearchResponse
from app.services.search_service import SearchService

router = APIRouter()


@router.get(
    "/search",
    summary="과제명, 학생 이름, 공지사항 키워드 통합 검색",
    status_code=status.HTTP_200_OK,
    response_model=SearchResponse,
    responses={
        400: {"model": ErrorDetail, "description": "keyword 누락 또는 2자 미만"},
        401: {"model": ErrorDetail, "description": "인증 토큰이 유효하지 않거나 만료됨"},
        403: {"model": ErrorDetail, "description": "STUDENT/TEACHER 외 role"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def search(
    keyword: str = Query(..., description="검색할 단어 (최소 2자 이상)"),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> SearchResponse:
    return await SearchService(db).search(user_id, keyword)
