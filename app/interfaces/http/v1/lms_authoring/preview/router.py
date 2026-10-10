"""Route to preview a draft step as a student."""

from app.interfaces.http.v1.lms_authoring.preview.handlers.preview_step import (
    preview_step,
)
from app.interfaces.http.v1.lms_authoring.preview.handlers.preview_video import (
    preview_video,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/preview/steps/{step_id}", preview_step, methods=["GET"])
router.add_api_route(
    "/preview/steps/{step_id}/blocks/{block_id}/video", preview_video, methods=["GET"]
)
