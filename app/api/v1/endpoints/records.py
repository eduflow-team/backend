from fastapi import APIRouter

router = APIRouter()


@router.get("/student/records", summary="단계별 최종 성적/피드백 조회")
def get_student_records():
    return {"status": "success", "data": {}}


@router.get("/teacher/records/grades", summary="학급 성적 관리 조회")
def get_teacher_grades():
    return {"status": "success", "data": {}}


@router.get("/teacher/records/students", summary="학급 전체 학생 현황 조회")
def get_teacher_students():
    return {"status": "success", "data": {}}
