"""Route to preview a draft step as a student."""

from app.interfaces.http.v1.lms_authoring.preview.handlers.preview_step import (
    preview_step,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/preview/steps/{step_id}", preview_step, methods=["GET"])
