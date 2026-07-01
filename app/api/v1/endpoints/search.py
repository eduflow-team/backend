from fastapi import APIRouter

router = APIRouter()


@router.get("/search", summary="과제명, 학생 이름, 공지사항 키워드 통합 검색")
def search():
    return {"status": "success", "data": {}}
