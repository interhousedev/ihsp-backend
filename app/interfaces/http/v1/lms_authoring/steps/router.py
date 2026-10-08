"""Routes of one step: draft, discard, checkpoints, history, restore, diff."""

from app.interfaces.http.v1.lms_authoring.steps.handlers.discard_step import (
    discard_step,
)
from app.interfaces.http.v1.lms_authoring.steps.handlers.get_step_draft import (
    get_step_draft,
)
from app.interfaces.http.v1.lms_authoring.steps.handlers.restore_revision import (
    restore_revision,
)
from app.interfaces.http.v1.lms_authoring.steps.handlers.save_checkpoint import (
    save_checkpoint,
)
from app.interfaces.http.v1.lms_authoring.steps.handlers.save_step_draft import (
    save_step_draft,
)
from app.interfaces.http.v1.lms_authoring.steps.handlers.step_diff import step_diff
from app.interfaces.http.v1.lms_authoring.steps.handlers.step_history import (
    step_history,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/lms/steps/{step_id}", tags=["lms-authoring"])
router.add_api_route("/draft", get_step_draft, methods=["GET"])
router.add_api_route("/draft", save_step_draft, methods=["PUT"])
router.add_api_route("/discard", discard_step, methods=["POST"])
router.add_api_route("/checkpoints", save_checkpoint, methods=["POST"])
router.add_api_route("/history", step_history, methods=["GET"])
router.add_api_route("/restore", restore_revision, methods=["POST"])
router.add_api_route("/diff", step_diff, methods=["GET"])
