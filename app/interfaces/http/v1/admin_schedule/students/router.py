"""Router of /v1/admin/students."""

from app.interfaces.http.v1.admin_schedule.students.handlers.import_confirm import (
    import_confirm,
)
from app.interfaces.http.v1.admin_schedule.students.handlers.import_preview import (
    import_preview,
)
from app.interfaces.http.v1.admin_schedule.students.handlers.list_students import (
    list_students,
)
from app.interfaces.http.v1.admin_schedule.students.schemas import (
    ImportConfirmResponse,
    ImportPreviewResponse,
    StudentPageResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/admin/students", tags=["admin-schedule"])
router.add_api_route(
    "", list_students, methods=["GET"], response_model=StudentPageResponse
)
router.add_api_route(
    "/import", import_preview, methods=["POST"], response_model=ImportPreviewResponse
)
router.add_api_route(
    "/import/{import_id}/confirm",
    import_confirm,
    methods=["POST"],
    response_model=ImportConfirmResponse,
)
