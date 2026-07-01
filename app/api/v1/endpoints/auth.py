from fastapi import APIRouter

router = APIRouter()


@router.post("/signup", summary="회원가입")
def signup():
    return {"status": "success", "data": {}}


@router.post("/classes", summary="학급 목록 조회")
def get_classes():
    return {"status": "success", "data": {}}


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
