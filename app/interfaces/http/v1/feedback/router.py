"""Routes of platform feedback (`/v1/feedback/*`, any signed-in user)."""

from app.interfaces.http.v1.feedback.handlers import (
    get_my_feedback,
    list_my_feedback,
    submit_feedback,
)
from app.interfaces.http.v1.feedback.schemas import (
    FeedbackDetailOut,
    FeedbackListOut,
    FeedbackOut,
)

from fastapi import APIRouter, status

router = APIRouter(prefix="/v1/feedback", tags=["feedback"])

router.add_api_route(
    "",
    submit_feedback.submit_feedback,
    methods=["POST"],
    status_code=status.HTTP_201_CREATED,
    response_model=FeedbackOut,
)
router.add_api_route(
    "/mine",
    list_my_feedback.list_my_feedback,
    methods=["GET"],
    response_model=FeedbackListOut,
)
router.add_api_route(
    "/{feedback_id}",
    get_my_feedback.get_my_feedback,
    methods=["GET"],
    response_model=FeedbackDetailOut,
)
