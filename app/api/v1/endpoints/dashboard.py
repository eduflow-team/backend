from fastapi import APIRouter

router = APIRouter()


@router.get("/student/dashboard/summary", summary="학생 대시보드 요약")
def get_student_dashboard_summary():
    return {"status": "success", "data": {}}


@router.get("/student/dashboard/assignments", summary="과제 목록 조회")
def get_student_dashboard_assignments():
    return {"status": "success", "data": {}}


@router.get("/teacher/dashboard/summary", summary="교사 대시보드 통계")
def get_teacher_dashboard_summary():
    return {"status": "success", "data": {}}


@router.get("/teacher/dashboard/students/unsubmitted", summary="미제출 학생 목록")
def get_unsubmitted_students():
    return {"status": "success", "data": {}}


@router.get("/teacher/dashboard/assignments", summary="생성 과제 목록")
def get_teacher_dashboard_assignments():
    return {"status": "success", "data": {}}


@router.delete("/teacher/dashboard/assignments/{id}", summary="과제 삭제")
def delete_teacher_assignment(id: int):
    return {"status": "success", "data": {}}
