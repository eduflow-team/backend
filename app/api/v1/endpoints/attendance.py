from fastapi import APIRouter

router = APIRouter()


@router.get("/student/attendance", summary="개인 누적 출석 기록")
def get_student_attendance():
    return {"status": "success", "data": {}}


@router.get("/teacher/attendance", summary="학급 출석부 명단 조회")
def get_teacher_attendance():
    return {"status": "success", "data": {}}


@router.patch("/teacher/attendance", summary="학급 출석부 수정 및 저장")
def update_teacher_attendance():
    return {"status": "success", "data": {}}
