"""Routes of the administrator student sync."""

from app.interfaces.http.v1.admin_student_sync.handlers.get_sync import get_sync
from app.interfaces.http.v1.admin_student_sync.handlers.post_sync import post_sync
from app.interfaces.http.v1.me_sync.schemas import SyncStatusResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/students", tags=["admin-sync"])

router.add_api_route(
    "/{user_id}/sync",
    post_sync,
    methods=["POST"],
    status_code=202,
    response_model=SyncStatusResponse,
)
router.add_api_route(
    "/{user_id}/sync",
    get_sync,
    methods=["GET"],
    response_model=SyncStatusResponse | None,
)
