"""Routes /v1/public/student-cards."""

from app.interfaces.http.v1.me_student_card.schemas import PublicStudentCardResponse
from app.interfaces.http.v1.public_student_cards.handlers import (
    get_public_student_card,
    get_public_student_card_photo,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/public/student-cards", tags=["student-card"])
router.add_api_route(
    "/{token}",
    get_public_student_card,
    methods=["GET"],
    response_model=PublicStudentCardResponse,
)
router.add_api_route(
    "/{token}/photo",
    get_public_student_card_photo,
    methods=["GET"],
    response_class=Response,
    responses={200: {"content": {"image/*": {}}}},
)
