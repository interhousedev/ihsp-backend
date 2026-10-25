"""Routes for reviewing and publishing pending changes."""

from app.interfaces.http.v1.lms_authoring.publishing.handlers.pending_changes import (
    pending_changes,
)
from app.interfaces.http.v1.lms_authoring.publishing.handlers.publish_course import (
    publish_course,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/pending", pending_changes, methods=["GET"])
router.add_api_route("/publish", publish_course, methods=["POST"])
