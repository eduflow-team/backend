from fastapi import APIRouter

router = APIRouter()


@router.get("/student/notices", summary="전체 공지사항 목록")
def get_student_notices():
    return {"status": "success", "data": {}}


@router.post("/teacher/notices", summary="새 공지사항 작성")
def create_teacher_notice():
    return {"status": "success", "data": {}}


@router.delete("/teacher/notices/{id}", summary="공지사항 삭제")
def delete_teacher_notice(id: int):
    return {"status": "success", "data": {}}
