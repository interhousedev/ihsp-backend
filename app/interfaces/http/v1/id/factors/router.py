"""Routes of the authenticator app (TOTP) and passkeys."""

from app.interfaces.http.v1.id.factors.handlers.login import (
    post_login_passkey,
    post_login_passkey_options,
    post_login_totp,
)
from app.interfaces.http.v1.id.factors.handlers.security import (
    delete_passkey,
    get_security,
    patch_passkey,
    post_passkey,
    post_passkey_options,
    post_password_login_disable,
    post_totp_confirm,
    post_totp_disable,
    post_totp_setup,
)
from app.interfaces.http.v1.id.factors.schemas import (
    PasskeyResponse,
    RecoveryCodesResponse,
    SecurityResponse,
    TotpSetupResponse,
    WebAuthnOptionsResponse,
)
from app.interfaces.http.v1.id.login.schemas import LoginResultResponse

from fastapi import APIRouter, Response

router = APIRouter(prefix="/v1/id", tags=["id-factors"])

router.add_api_route(
    "/me/security", get_security, methods=["GET"], response_model=SecurityResponse
)
router.add_api_route(
    "/me/totp/setup",
    post_totp_setup,
    methods=["POST"],
    response_model=TotpSetupResponse,
)
router.add_api_route(
    "/me/totp/confirm",
    post_totp_confirm,
    methods=["POST"],
    response_model=RecoveryCodesResponse,
)
router.add_api_route(
    "/me/totp/disable",
    post_totp_disable,
    methods=["POST"],
    response_model=SecurityResponse,
)
router.add_api_route(
    "/me/passkeys/options",
    post_passkey_options,
    methods=["POST"],
    response_model=WebAuthnOptionsResponse,
)
router.add_api_route(
    "/me/passkeys", post_passkey, methods=["POST"], response_model=PasskeyResponse
)
router.add_api_route(
    "/me/passkeys/{id}",
    patch_passkey,
    methods=["PATCH"],
    response_model=PasskeyResponse,
)
router.add_api_route(
    "/me/passkeys/{id}",
    delete_passkey,
    methods=["DELETE"],
    status_code=204,
    response_class=Response,
)
router.add_api_route(
    "/me/password-login/disable",
    post_password_login_disable,
    methods=["POST"],
    response_model=SecurityResponse,
)
router.add_api_route(
    "/login/totp",
    post_login_totp,
    methods=["POST"],
    response_model=LoginResultResponse,
)
router.add_api_route(
    "/login/passkey/options",
    post_login_passkey_options,
    methods=["POST"],
    response_model=WebAuthnOptionsResponse,
)
router.add_api_route(
    "/login/passkey",
    post_login_passkey,
    methods=["POST"],
    response_model=LoginResultResponse,
)
