from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import get_db
from app.schemas.auth import (
    ClassItem,
    ClassListResponse,
    ErrorDetail,
    SignupRequest,
    SignupResponse,
)
from app.services.auth_service import AuthService
from app.services.class_service import ClassService

router = APIRouter()


@router.post(
    "/signup",
    summary="회원가입",
    status_code=status.HTTP_201_CREATED,
    response_model=SignupResponse,
    responses={
        400: {"model": ErrorDetail, "description": "필수 필드 누락 또는 이메일 형식 오류"},
        403: {"model": ErrorDetail, "description": "교사 가입 인증 코드 오류"},
        409: {"model": ErrorDetail, "description": "이미 존재하는 이메일"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    user = await AuthService(db).signup(payload)
    return SignupResponse(user_id=user.user_id, email=user.email, created_at=user.created_at)


@router.get(
    "/classes",
    summary="학급 목록 조회",
    status_code=status.HTTP_200_OK,
    response_model=ClassListResponse,
    responses={500: {"model": ErrorDetail, "description": "서버 내부 오류"}},
)
async def get_classes(db: AsyncSession = Depends(get_db)) -> ClassListResponse:
    classes = await ClassService(db).list_classes()
    return ClassListResponse(
        classes=[
            ClassItem(class_id=c.class_id, grade=c.grade, class_number=c.class_number)
            for c in classes
        ]
    )


@router.post("/login", summary="로그인")
def login():
    return {"status": "success", "data": {}}


@router.post("/social/{provider}", summary="소셜 로그인")
def social_login(provider: str):
    return {"status": "success", "data": {}}


@router.post("/logout", summary="로그아웃")
def logout():
    return {"status": "success", "data": {}}


@router.get("/me", summary="내 정보 조회")
def get_me():
    return {"status": "success", "data": {}}


@router.delete("/leave", summary="회원 탈퇴")
def leave():
    return {"status": "success", "data": {}}


@router.post("/refresh", summary="토큰 재발급")
def refresh():
    return {"status": "success", "data": {}}
