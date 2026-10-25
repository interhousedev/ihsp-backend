"""Routes of the course draft: meta, outline, steps, discard."""

from app.interfaces.http.v1.lms_authoring.draft.handlers.apply_outline import (
    apply_outline,
)
from app.interfaces.http.v1.lms_authoring.draft.handlers.create_step import create_step
from app.interfaces.http.v1.lms_authoring.draft.handlers.discard_course import (
    discard_course,
)
from app.interfaces.http.v1.lms_authoring.draft.handlers.get_course_draft import (
    get_course_draft,
)
from app.interfaces.http.v1.lms_authoring.draft.handlers.update_meta import update_meta

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/courses/{course_id}", tags=["lms-authoring"])
router.add_api_route("/draft", get_course_draft, methods=["GET"])
router.add_api_route("/draft/meta", update_meta, methods=["PUT"])
router.add_api_route("/draft/outline", apply_outline, methods=["POST"])
router.add_api_route("/steps", create_step, methods=["POST"])
router.add_api_route("/discard", discard_course, methods=["POST"])
