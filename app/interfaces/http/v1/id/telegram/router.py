"""Routes of the Telegram mini app login page."""

from app.interfaces.http.v1.id.login.schemas import LoginResultResponse, SentResponse
from app.interfaces.http.v1.id.telegram.handlers.post_telegram_login import (
    post_telegram_login,
)
from app.interfaces.http.v1.id.telegram.handlers.post_telegram_otp_request import (
    post_telegram_otp_request,
)
from app.interfaces.http.v1.id.telegram.handlers.post_telegram_status import (
    post_telegram_status,
)
from app.interfaces.http.v1.id.telegram.schemas import (
    TelegramLinkedResponse,
    TelegramStatusResponse,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/id/telegram", tags=["id-telegram"])

router.add_api_route(
    "/status",
    post_telegram_status,
    methods=["POST"],
    response_model=TelegramStatusResponse,
)
router.add_api_route(
    "/otp/request",
    post_telegram_otp_request,
    methods=["POST"],
    status_code=202,
    response_model=SentResponse,
)
router.add_api_route(
    "/login",
    post_telegram_login,
    methods=["POST"],
    response_model=TelegramLinkedResponse | LoginResultResponse,
)
