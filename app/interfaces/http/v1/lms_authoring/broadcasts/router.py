"""Routes where course admins update the enrolled students."""

from app.interfaces.http.v1.lms_authoring.broadcasts.handlers.list_broadcasts import (
    list_broadcasts,
)
from app.interfaces.http.v1.lms_authoring.broadcasts.handlers.send_broadcast import (
    send_broadcast,
)
from app.interfaces.http.v1.lms_authoring.broadcasts.schemas import (
    CourseBroadcastResponse,
)

from fastapi import APIRouter

router = APIRouter(
    prefix="/v1/staff/lms/courses/{course_id}/broadcasts", tags=["lms-authoring"]
)
router.add_api_route(
    "",
    send_broadcast,
    methods=["POST"],
    status_code=201,
    response_model=CourseBroadcastResponse,
)
router.add_api_route(
    "", list_broadcasts, methods=["GET"], response_model=list[CourseBroadcastResponse]
)
