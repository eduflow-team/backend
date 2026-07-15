from fastapi import APIRouter, Depends, File, Form, UploadFile, status
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
from app.schemas.dashboard import ErrorDetail
from app.schemas.stage2 import Stage2CreateResponse
from app.services.assignment_service import AssignmentService
from app.services.stage2_service import Stage2Service

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


@router.get("/student/assignments/{id}/step2", summary="2단계 과제 상세")
def get_step2_assignment(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step2/highlight", summary="오답 하이라이트 제출")
def submit_step2_highlight(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step2/correction", summary="빈칸 정답 수정 제출")
def submit_step2_correction(id: int):
    return {"status": "success", "data": {}}


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
    question: str = Form(...),
    guideline: str = Form(...),
    default_chunk_size: int = Form(200),
    default_top_k: int = Form(2),
    default_temperature: float = Form(0.9),
    file: UploadFile = File(...),
    user_id: int = Depends(get_current_user_id),
    db: AsyncSession = Depends(get_db),
) -> Stage1CreateResponse:
    return await AssignmentService(db).create_step1_assignment(
        user_id,
        class_id=class_id,
        subject=subject,
        question=question,
        guideline=guideline,
        default_chunk_size=default_chunk_size,
        default_top_k=default_top_k,
        default_temperature=default_temperature,
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
    hallucination_types: str = Form(
        ...,
        description='JSON 배열. 예: ["PERSONA_BIAS","RETRIEVAL_ERROR"]',
    ),
    expected_error_count: int = Form(..., ge=1, le=5),
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
        hallucination_types_raw=hallucination_types,
        expected_error_count=expected_error_count,
        file=file,
    )
