"""Route to preview a draft step as a student."""

from app.interfaces.http.v1.lms_authoring.preview.handlers.h5p import (
    preview_h5p,
    upload_h5p,
)
from app.interfaces.http.v1.lms_authoring.preview.handlers.html_widget import (
    preview_html_widget,
    upload_html_widget,
)
from app.interfaces.http.v1.lms_authoring.preview.handlers.preview_step import (
    preview_step,
)
from app.interfaces.http.v1.lms_authoring.preview.handlers.preview_video import (
    preview_video,
    preview_video_captions,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/preview/steps/{step_id}", preview_step, methods=["GET"])
router.add_api_route(
    "/preview/steps/{step_id}/blocks/{block_id}/video", preview_video, methods=["GET"]
)
router.add_api_route(
    "/preview/steps/{step_id}/blocks/{block_id}/captions",
    preview_video_captions,
    methods=["GET"],
)
router.add_api_route(
    "/preview/steps/{step_id}/blocks/{block_id}/h5p", preview_h5p, methods=["GET"]
)
router.add_api_route("/h5p", upload_h5p, methods=["POST"])
router.add_api_route(
    "/preview/steps/{step_id}/blocks/{block_id}/html-widget",
    preview_html_widget,
    methods=["GET"],
)
router.add_api_route("/html-widgets", upload_html_widget, methods=["POST"])
