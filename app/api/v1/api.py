from fastapi import APIRouter

from app.api.v1.endpoints import (
    assignments,
    attendance,
    auth,
    dashboard,
    notices,
    records,
    search,
)

api_router = APIRouter()

api_router.include_router(auth.router, prefix="/auth", tags=["Auth"])
api_router.include_router(dashboard.router, tags=["Dashboard"])
api_router.include_router(assignments.router, tags=["Assignments"])
api_router.include_router(records.router, tags=["Records"])
api_router.include_router(attendance.router, tags=["Attendance"])
api_router.include_router(notices.router, tags=["Notices"])
api_router.include_router(search.router, tags=["Search"])
