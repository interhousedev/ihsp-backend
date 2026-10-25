"""Routes under ``/v1/admin/work-offs``."""

from app.interfaces.http.v1.admin_work_offs.handlers.get_work_off_stats import (
    get_work_off_stats,
)
from app.interfaces.http.v1.admin_work_offs.handlers.list_admin_work_offs import (
    list_admin_work_offs,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/work-offs", tags=["admin-work-offs"])
router.add_api_route("/stats", get_work_off_stats, methods=["GET"])
router.add_api_route("", list_admin_work_offs, methods=["GET"])
