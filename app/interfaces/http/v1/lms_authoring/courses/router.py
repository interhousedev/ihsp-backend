"""Routes that create courses and change their settings."""

from app.interfaces.http.v1.lms_authoring.courses.handlers.create_course import (
    create_course,
)
from app.interfaces.http.v1.lms_authoring.courses.handlers.rotate_invite_code import (
    rotate_invite_code,
)
from app.interfaces.http.v1.lms_authoring.courses.handlers.update_settings import (
    update_settings,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms", tags=["lms-authoring"])
router.add_api_route("/courses", create_course, methods=["POST"])
router.add_api_route(
    "/courses/{course_id}/settings", update_settings, methods=["PATCH"]
)
router.add_api_route(
    "/courses/{course_id}/invite-code", rotate_invite_code, methods=["POST"]
)
