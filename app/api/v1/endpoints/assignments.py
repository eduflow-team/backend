from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_user_id
from app.db.session import get_db
from app.schemas.assignments import (
    Stage1AssignmentDetailResponse,
    Stage1ChatRequest,
    Stage1ChatResponse,
    Stage1CreateResponse,
    Stage1SubmitRequest,
    Stage1SubmitResponse,
)
from app.schemas.stage4 import (
    Stage4AssignmentDetailResponse,
    Stage4ChatRequest,
    Stage4ChatResponse,
    Stage4CreateRequest,
    Stage4CreateResponse,
    Stage4SubmitRequest,
    Stage4SubmitResponse,
)
from app.schemas.dashboard import ErrorDetail
from app.schemas.stage2 import (
    Stage2AssignmentDetailResponse,
    Stage2CreateResponse,
    Stage2SetCreateResponse,
    Stage2SetDetailResponse,
    Stage2SetPublishRequest,
    Stage2SetPublishResponse,
    Step2CorrectionRequest,
    Step2CorrectionResponse,
    Step2HighlightRequest,
    Step2HighlightResponse,
)
from app.services.assignment_service import AssignmentService
from app.services.stage2_service import Stage2Service
from app.services.stage4_service import Stage4Service

router = APIRouter()


@router.get(
    "/student/assignments/{id}/step1",
    summary="1단계 과제 상세",
    status_code=status.HTTP_200_OK,
    response_model=Stage1AssignmentDetailResponse,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step1_assignment(
    id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage1AssignmentDetailResponse:
    return await AssignmentService(db).get_step1_assignment(user_id, id)


@router.get(
    "/student/assignments/{id}/step1/document",
    summary="1단계 학습 자료(원본 PDF 등) 조회",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step1_document(
    id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    path, filename, media_type = await AssignmentService(db).get_step1_document(
        user_id, id
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


@router.post(
    "/student/assignments/{id}/step1/chat",
    summary="AI 질의응답",
    status_code=status.HTTP_200_OK,
    response_model=Stage1ChatResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        503: {"model": ErrorDetail},
        504: {"model": ErrorDetail},
    },
)
async def chat_step1_assignment(
    id: int,
    payload: Stage1ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage1ChatResponse:
    return await AssignmentService(db).chat_step1(user_id, id, payload)


@router.post(
    "/student/assignments/{id}/step1/submit",
    summary="최종 답변 제출 및 채점",
    status_code=status.HTTP_200_OK,
    response_model=Stage1SubmitResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def submit_step1_assignment(
    id: int,
    payload: Stage1SubmitRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage1SubmitResponse:
    return await AssignmentService(db).submit_step1(user_id, id, payload)


@router.get(
    "/student/assignments/{id}/step2",
    summary="2단계 과제 상세",
    status_code=status.HTTP_200_OK,
    response_model=Stage2AssignmentDetailResponse,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step2_assignment(
    id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage2AssignmentDetailResponse:
    return await Stage2Service(db).get_step2_assignment(user_id, id)


@router.get(
    "/student/assignments/{id}/step2/document",
    summary="2단계 참고 문서(PDF) 조회",
    status_code=status.HTTP_200_OK,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step2_reference_document(
    id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> FileResponse:
    path, filename, media_type = await Stage2Service(db).get_step2_reference_document(
        user_id, id
    )
    return FileResponse(
        path,
        media_type=media_type,
        filename=filename,
        content_disposition_type="inline",
    )


@router.post(
    "/student/assignments/{id}/step2/highlight",
    summary="오답 하이라이트 제출",
    status_code=status.HTTP_200_OK,
    response_model=Step2HighlightResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
    },
)
async def submit_step2_highlight(
    id: int,
    payload: Step2HighlightRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Step2HighlightResponse:
    return await Stage2Service(db).submit_highlight(user_id, id, payload)


@router.post(
    "/student/assignments/{id}/step2/correction",
    summary="빈칸 정답 수정 제출",
    status_code=status.HTTP_200_OK,
    response_model=Step2CorrectionResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
    },
)
async def submit_step2_correction(
    id: int,
    payload: Step2CorrectionRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Step2CorrectionResponse:
    return await Stage2Service(db).submit_correction(user_id, id, payload)


@router.post(
    "/teacher/assignments/step1",
    summary="과제 생성 및 문서 벡터화",
    status_code=status.HTTP_201_CREATED,
    response_model=Stage1CreateResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        413: {"model": ErrorDetail},
        415: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
    },
)
async def create_step1_assignment(
    class_id: int = Form(..., description="과제를 배정할 학급 ID"),
    subject: str = Form(...),
    question: str = Form(..., description="학생이 풀 퀴즈 문제 1개"),
    answer: str = Form(..., description="정답 1개 (교과서 표현)"),
    due_at: datetime = Form(..., description="마감 일시 (ISO 8601)"),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage1CreateResponse:
    """교사 문제·정답 + 학습 자료 업로드. 시작 파라미터는 서버 고정(50/2/1.0)."""
    return await AssignmentService(db).create_step1_assignment(
        user_id,
        class_id=class_id,
        subject=subject,
        question=question,
        answer=answer,
        due_at=due_at,
        file=file,
    )


@router.post(
    "/teacher/assignments/step2",
    summary="2단계 과제 생성",
    status_code=status.HTTP_201_CREATED,
    response_model=Stage2CreateResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        413: {"model": ErrorDetail},
        415: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
        503: {"model": ErrorDetail},
    },
)
async def create_step2_assignment(
    title: str = Form(...),
    subject: str = Form(...),
    question: str = Form(...),
    persona: str = Form(..., max_length=100),
    due_at: datetime = Form(..., description="마감 일시 (ISO 8601)"),
    hallucination_types: str = Form(
        ...,
        description='JSON 배열. 예: ["PERSONA_BIAS","RETRIEVAL_ERROR"]',
    ),
    expected_error_count: int = Form(1, ge=1, le=1),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage2CreateResponse:
    return await Stage2Service(db).create_step2_assignment(
        user_id,
        title=title,
        subject=subject,
        question=question,
        persona=persona,
        due_at=due_at,
        hallucination_types_raw=hallucination_types,
        expected_error_count=expected_error_count,
        file=file,
    )


@router.post(
    "/teacher/assignments/step2/set",
    summary="2단계 카드 세트 생성",
    status_code=status.HTTP_201_CREATED,
    response_model=Stage2SetCreateResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        413: {"model": ErrorDetail},
        415: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
        503: {"model": ErrorDetail},
    },
)
async def create_step2_set(
    title: str = Form(...),
    subject: str = Form(...),
    question: str = Form(...),
    persona: str = Form(..., max_length=100),
    due_at: datetime = Form(..., description="마감 일시 (ISO 8601)"),
    hallucination_types: str = Form(
        ...,
        description='JSON 배열. 예: ["PERSONA_BIAS","RETRIEVAL_ERROR"]',
    ),
    card_count: int = Form(..., ge=1, le=3),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage2SetCreateResponse:
    return await Stage2Service(db).create_step2_set(
        user_id,
        title=title,
        subject=subject,
        question=question,
        persona=persona,
        due_at=due_at,
        hallucination_types_raw=hallucination_types,
        card_count=card_count,
        file=file,
    )


@router.get(
    "/teacher/assignments/step2/set/{set_id}",
    summary="2단계 카드 세트 조회",
    status_code=status.HTTP_200_OK,
    response_model=Stage2SetDetailResponse,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step2_set(
    set_id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage2SetDetailResponse:
    return await Stage2Service(db).get_step2_set(user_id, set_id)


@router.patch(
    "/teacher/assignments/step2/set/{set_id}",
    summary="2단계 카드 세트 배포",
    status_code=status.HTTP_200_OK,
    response_model=Stage2SetPublishResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def publish_step2_set(
    set_id: int,
    payload: Stage2SetPublishRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage2SetPublishResponse:
    return await Stage2Service(db).publish_step2_set(user_id, set_id, payload)


@router.post(
    "/teacher/assignments/step4",
    summary="4단계 과제 생성",
    status_code=status.HTTP_201_CREATED,
    response_model=Stage4CreateResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        500: {"model": ErrorDetail},
    },
)
async def create_step4_assignment(
    payload: Stage4CreateRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage4CreateResponse:
    return await Stage4Service(db).create_step4_assignment(user_id=user_id, payload=payload)


@router.get(
    "/student/assignments/{id}/step4",
    summary="4단계 과제 상세 조회",
    status_code=status.HTTP_200_OK,
    response_model=Stage4AssignmentDetailResponse,
    responses={
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def get_step4_assignment(
    id: int,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage4AssignmentDetailResponse:
    return await Stage4Service(db).get_step4_assignment(user_id=user_id, assignment_id=id)


@router.post(
    "/student/assignments/{id}/step4/chat",
    summary="공격 채팅 (프롬프트 인젝션)",
    status_code=status.HTTP_200_OK,
    response_model=Stage4ChatResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
        503: {"model": ErrorDetail},
    },
)
async def chat_step4_assignment(
    id: int,
    payload: Stage4ChatRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage4ChatResponse:
    return await Stage4Service(db).chat_step4(
        user_id=user_id,
        assignment_id=id,
        attack_prompt=payload.attack_prompt,
    )


@router.post(
    "/student/assignments/{id}/step4/submit",
    summary="보안 분석 보고서 제출",
    status_code=status.HTTP_200_OK,
    response_model=Stage4SubmitResponse,
    responses={
        400: {"model": ErrorDetail},
        401: {"model": ErrorDetail},
        403: {"model": ErrorDetail},
        404: {"model": ErrorDetail},
    },
)
async def submit_step4_assignment(
    id: int,
    payload: Stage4SubmitRequest,
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage4SubmitResponse:
    return await Stage4Service(db).submit_step4_report(
        user_id=user_id,
        assignment_id=id,
        payload=payload,
    )
