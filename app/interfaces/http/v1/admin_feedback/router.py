"""Routes of platform feedback (`/v1/admin/feedback/*`, administrators only)."""

from app.interfaces.http.v1.admin_feedback.handlers import (
    get_feedback,
    list_feedback,
    respond_to_feedback,
    set_feedback_status,
)
from app.interfaces.http.v1.feedback.schemas import (
    AdminFeedbackDetail,
    AdminFeedbackListOut,
    ResponseOut,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/admin/feedback", tags=["admin-feedback"])

router.add_api_route(
    "",
    list_feedback.list_feedback,
    methods=["GET"],
    response_model=AdminFeedbackListOut,
)
router.add_api_route(
    "/{feedback_id}",
    get_feedback.get_feedback,
    methods=["GET"],
    response_model=AdminFeedbackDetail,
)
router.add_api_route(
    "/{feedback_id}",
    set_feedback_status.set_feedback_status,
    methods=["PATCH"],
    response_model=AdminFeedbackDetail,
)
router.add_api_route(
    "/{feedback_id}/responses",
    respond_to_feedback.respond_to_feedback,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=ResponseOut,
)
