"""Routes that create courses and change their settings."""

from app.interfaces.http.v1.lms_authoring.courses.handlers.access import (
    get_access,
    set_course_access,
    set_step_access,
)
from app.interfaces.http.v1.lms_authoring.courses.handlers.create_course import (
    create_course,
)
from app.interfaces.http.v1.lms_authoring.courses.handlers.rotate_invite_code import (
    rotate_invite_code,
)
from app.interfaces.http.v1.lms_authoring.courses.handlers.settings import (
    get_link_report,
    get_settings,
    regenerate_join_code,
    start_link_check,
    update_details,
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
router.add_api_route("/courses/{course_id}/settings", get_settings, methods=["GET"])
router.add_api_route(
    "/courses/{course_id}/settings/details", update_details, methods=["PATCH"]
)
router.add_api_route(
    "/courses/{course_id}/settings/join-code", regenerate_join_code, methods=["POST"]
)
router.add_api_route(
    "/courses/{course_id}/link-check", start_link_check, methods=["POST"]
)
router.add_api_route(
    "/courses/{course_id}/link-check", get_link_report, methods=["GET"]
)
router.add_api_route("/courses/{course_id}/access", get_access, methods=["GET"])
router.add_api_route("/courses/{course_id}/access", set_course_access, methods=["PUT"])
router.add_api_route(
    "/courses/{course_id}/steps/{step_id}/access", set_step_access, methods=["PUT"]
)
