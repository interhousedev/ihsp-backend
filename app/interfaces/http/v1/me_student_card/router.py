"""Routes /v1/me/student-card."""

from app.interfaces.http.v1.me_student_card.handlers import (
    get_student_card,
    get_student_card_apple_pass,
    get_student_card_google_link,
    regenerate_student_card_token,
)
from app.interfaces.http.v1.me_student_card.schemas import (
    GoogleWalletLinkResponse,
    StudentCardResponse,
    StudentCardTokenResponse,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/me/student-card", tags=["student-card"])
router.add_api_route(
    "", get_student_card, methods=["GET"], response_model=StudentCardResponse
)
router.add_api_route(
    "/tokens",
    regenerate_student_card_token,
    methods=["POST"],
    response_model=StudentCardTokenResponse,
)
router.add_api_route(
    "/wallet/apple",
    get_student_card_apple_pass,
    methods=["GET"],
    response_class=Response,
    responses={200: {"content": {"application/vnd.apple.pkpass": {}}}},
)
router.add_api_route(
    "/wallet/google",
    get_student_card_google_link,
    methods=["POST"],
    response_model=GoogleWalletLinkResponse,
)
