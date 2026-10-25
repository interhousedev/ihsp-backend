"""Routes of password, OTP and login recovery."""

from app.interfaces.http.v1.id.recovery.handlers.post_login_recovery import (
    post_login_recovery,
)
from app.interfaces.http.v1.id.recovery.handlers.post_otp_cancel import (
    post_otp_cancel,
)
from app.interfaces.http.v1.id.recovery.handlers.post_otp_confirm import (
    post_otp_confirm,
)
from app.interfaces.http.v1.id.recovery.handlers.post_otp_request import (
    post_otp_request,
)
from app.interfaces.http.v1.id.recovery.handlers.post_password_confirm import (
    post_password_confirm,
)
from app.interfaces.http.v1.id.recovery.handlers.post_password_request import (
    post_password_request,
)
from app.interfaces.http.v1.id.recovery.schemas import (
    OtpRecoveryConfirmResponse,
    PasswordConfirmResponse,
)

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/id/recovery", tags=["id-recovery"])

router.add_api_route(
    "/password/request",
    post_password_request,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
router.add_api_route(
    "/password/confirm",
    post_password_confirm,
    methods=["POST"],
    response_model=PasswordConfirmResponse,
)
router.add_api_route(
    "/otp/request",
    post_otp_request,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
router.add_api_route(
    "/otp/confirm",
    post_otp_confirm,
    methods=["POST"],
    response_model=OtpRecoveryConfirmResponse,
)
router.add_api_route(
    "/otp/cancel",
    post_otp_cancel,
    methods=["POST"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/login",
    post_login_recovery,
    methods=["POST"],
    status_code=202,
    response_class=Response,
)
