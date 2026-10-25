"""Routes under /v1/id/me."""

from app.interfaces.http.v1.id.account.handlers.delete_session import delete_session
from app.interfaces.http.v1.id.account.handlers.delete_telegram import delete_telegram
from app.interfaces.http.v1.id.account.handlers.get_activity import get_activity
from app.interfaces.http.v1.id.account.handlers.get_me import get_me
from app.interfaces.http.v1.id.account.handlers.get_sessions import get_sessions
from app.interfaces.http.v1.id.account.handlers.get_telegram import get_telegram
from app.interfaces.http.v1.id.account.handlers.patch_preferences import (
    patch_preferences,
)
from app.interfaces.http.v1.id.account.handlers.patch_telegram import patch_telegram
from app.interfaces.http.v1.id.account.handlers.post_email_change import (
    post_email_change,
)
from app.interfaces.http.v1.id.account.handlers.post_email_change_confirm import (
    post_email_change_confirm,
)
from app.interfaces.http.v1.id.account.handlers.post_otp_disable import post_otp_disable
from app.interfaces.http.v1.id.account.handlers.post_otp_enable import post_otp_enable
from app.interfaces.http.v1.id.account.handlers.post_otp_enable_confirm import (
    post_otp_enable_confirm,
)
from app.interfaces.http.v1.id.account.handlers.post_password import post_password
from app.interfaces.http.v1.id.account.handlers.post_revoke_others import (
    post_revoke_others,
)
from app.interfaces.http.v1.id.account.handlers.post_step_up import post_step_up
from app.interfaces.http.v1.id.account.schemas import UserMeResponse
from app.interfaces.http.v1.id.schemas import (
    AuditItemResponse,
    SessionItemResponse,
    TelegramAccountResponse,
)
from app.shared.contracts.identity import UserPreferences
from app.shared.pagination import Page

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/id/me", tags=["id-account"])

router.add_api_route("", get_me, methods=["GET"], response_model=UserMeResponse)
router.add_api_route(
    "/preferences", patch_preferences, methods=["PATCH"], response_model=UserPreferences
)
router.add_api_route(
    "/password",
    post_password,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/sessions",
    get_sessions,
    methods=["GET"],
    response_model=list[SessionItemResponse],
)
router.add_api_route(
    "/sessions/revoke-others",
    post_revoke_others,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/sessions/{id}",
    delete_session,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/telegram",
    get_telegram,
    methods=["GET"],
    response_model=list[TelegramAccountResponse],
)
router.add_api_route(
    "/telegram/{telegram_user_id}",
    patch_telegram,
    methods=["PATCH"],
    response_model=TelegramAccountResponse,
)
router.add_api_route(
    "/telegram/{telegram_user_id}",
    delete_telegram,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/otp/enable",
    post_otp_enable,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
router.add_api_route(
    "/otp/enable/confirm",
    post_otp_enable_confirm,
    methods=["POST"],
    response_model=UserMeResponse,
)
router.add_api_route(
    "/otp/disable", post_otp_disable, methods=["POST"], response_model=UserMeResponse
)
router.add_api_route(
    "/email/change",
    post_email_change,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
router.add_api_route(
    "/email/change/confirm",
    post_email_change_confirm,
    methods=["POST"],
    response_model=UserMeResponse,
)
router.add_api_route(
    "/activity",
    get_activity,
    methods=["GET"],
    response_model=Page[AuditItemResponse],
)
router.add_api_route(
    "/step-up",
    post_step_up,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
