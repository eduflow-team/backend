from fastapi import APIRouter, Depends, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id, get_current_user_id_for_me
from app.db.session import get_db
from app.schemas.auth import (
    ClassItem,
    ClassListResponse,
    ErrorDetail,
    LoginRequest,
    LoginResponse,
    LogoutRequest,
    MeResponse,
    RefreshRequest,
    RefreshResponse,
    SignupRequest,
    SignupResponse,
    SocialLoginRequest,
    SocialProvider,
    SocialSignupRequest,
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


@router.post(
    "/login",
    summary="로그인",
    status_code=status.HTTP_200_OK,
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorDetail, "description": "필수 필드 누락 또는 이메일 형식 오류"},
        401: {"model": ErrorDetail, "description": "이메일 또는 비밀번호 불일치"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def login(payload: LoginRequest, db: AsyncSession = Depends(get_db)) -> LoginResponse:
    tokens = await AuthService(db).login(payload)
    return LoginResponse(
        user_id=tokens.user.user_id,
        role=tokens.user.role,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/social/{provider}",
    summary="소셜 로그인",
    status_code=status.HTTP_200_OK,
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorDetail, "description": "지원하지 않는 provider 또는 필수 필드 누락"},
        401: {"model": ErrorDetail, "description": "만료되었거나 유효하지 않은 소셜 토큰"},
        404: {"model": ErrorDetail, "description": "연동된 계정 없음 (회원가입 필요)"},
        502: {"model": ErrorDetail, "description": "소셜 인증 서버와의 통신 실패"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def social_login(
    provider: SocialProvider,
    payload: SocialLoginRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    tokens = await AuthService(db).social_login(provider, payload.social_token)
    return LoginResponse(
        user_id=tokens.user.user_id,
        role=tokens.user.role,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/social/{provider}/signup",
    summary="소셜 회원가입",
    status_code=status.HTTP_201_CREATED,
    response_model=LoginResponse,
    responses={
        400: {"model": ErrorDetail, "description": "필수 필드 누락 또는 지원하지 않는 provider"},
        401: {"model": ErrorDetail, "description": "만료되었거나 유효하지 않은 소셜 토큰"},
        403: {"model": ErrorDetail, "description": "교사 가입 인증 코드 오류"},
        409: {"model": ErrorDetail, "description": "이미 가입된 소셜 계정"},
        502: {"model": ErrorDetail, "description": "소셜 인증 서버와의 통신 실패"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def social_signup(
    provider: SocialProvider,
    payload: SocialSignupRequest,
    db: AsyncSession = Depends(get_db),
) -> LoginResponse:
    tokens = await AuthService(db).social_signup(provider, payload)
    return LoginResponse(
        user_id=tokens.user.user_id,
        role=tokens.user.role,
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )


@router.post(
    "/logout",
    summary="로그아웃",
    status_code=status.HTTP_200_OK,
    responses={
        400: {"model": ErrorDetail, "description": "필수 파라미터(refresh_token) 누락 또는 형식 오류"},
        401: {"model": ErrorDetail, "description": "유효하지 않거나 이미 만료된 토큰"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def logout(
    payload: LogoutRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> dict:
    await AuthService(db).logout(user_id, payload.refresh_token)
    return {}


@router.get(
    "/me",
    summary="내 정보 조회",
    status_code=status.HTTP_200_OK,
    response_model=MeResponse,
    responses={
        401: {"model": ErrorDetail, "description": "인증 토큰(Access Token) 누락 또는 만료"},
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def get_me(
    user_id: int = Depends(get_current_user_id_for_me),
    db: AsyncSession = Depends(get_db),
) -> MeResponse:
    user = await AuthService(db).get_me(user_id)
    return MeResponse(user_id=user.user_id, name=user.name, email=user.email, role=user.role)


@router.delete("/leave", summary="회원 탈퇴")
def leave():
    return {"status": "success", "data": {}}


@router.post(
    "/refresh",
    summary="토큰 재발급",
    status_code=status.HTTP_200_OK,
    response_model=RefreshResponse,
    responses={
        400: {"model": ErrorDetail, "description": "refresh_token이 요청에 포함되지 않음"},
        401: {
            "model": ErrorDetail,
            "description": "Refresh Token이 만료·조작되었거나 이미 사용된(RTR 위반) 토큰",
        },
        500: {"model": ErrorDetail, "description": "서버 내부 오류"},
    },
)
async def refresh(payload: RefreshRequest, db: AsyncSession = Depends(get_db)) -> RefreshResponse:
    tokens = await AuthService(db).refresh(payload.refresh_token)
    return RefreshResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        expires_in=tokens.expires_in,
    )
