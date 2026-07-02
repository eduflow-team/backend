from fastapi import APIRouter

router = APIRouter()


@router.get("/student/assignments/{id}/step1", summary="1단계 과제 상세")
def get_step1_assignment(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step1/chat", summary="AI 질의응답")
def chat_step1_assignment(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step1/submit", summary="최종 답변 제출 및 채점")
def submit_step1_assignment(id: int):
    return {"status": "success", "data": {}}


@router.get("/student/assignments/{id}/step2", summary="2단계 과제 상세")
def get_step2_assignment(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step2/highlight", summary="오답 하이라이트 제출")
def submit_step2_highlight(id: int):
    return {"status": "success", "data": {}}


@router.post("/student/assignments/{id}/step2/correction", summary="빈칸 정답 수정 제출")
def submit_step2_correction(id: int):
    return {"status": "success", "data": {}}


@router.post("/teacher/assignments/step1", summary="과제 생성 및 문서 벡터화")
def create_step1_assignment():
    return {"status": "success", "data": {}}


@router.post("/teacher/assignments/step2", summary="2단계 과제 생성")
def create_step2_assignment():
    return {"status": "success", "data": {}}