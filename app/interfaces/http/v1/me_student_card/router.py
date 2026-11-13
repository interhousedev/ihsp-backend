"""Routes /v1/me/student-card."""

from app.interfaces.http.v1.me_student_card.handlers import (
    get_student_card,
    issue_student_card_token,
)
from app.interfaces.http.v1.me_student_card.schemas import (
    StudentCardResponse,
    StudentCardTokenResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/me/student-card", tags=["student-card"])
router.add_api_route(
    "", get_student_card, methods=["GET"], response_model=StudentCardResponse
)
router.add_api_route(
    "/tokens",
    issue_student_card_token,
    methods=["POST"],
    response_model=StudentCardTokenResponse,
)
