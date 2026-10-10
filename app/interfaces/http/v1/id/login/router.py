"""Routes of the Hydra login, consent and logout app."""

from app.interfaces.http.v1.id.login.handlers.get_consent import get_consent
from app.interfaces.http.v1.id.login.handlers.get_login import get_login
from app.interfaces.http.v1.id.login.handlers.get_logout import get_logout
from app.interfaces.http.v1.id.login.handlers.post_consent import post_consent
from app.interfaces.http.v1.id.login.handlers.post_consent_otp import (
    post_consent_otp,
)
from app.interfaces.http.v1.id.login.handlers.post_login import post_login
from app.interfaces.http.v1.id.login.handlers.post_login_otp import post_login_otp
from app.interfaces.http.v1.id.login.handlers.post_login_password import (
    post_login_password,
)
from app.interfaces.http.v1.id.login.handlers.request_login_otp import (
    request_login_otp,
)
from app.interfaces.http.v1.id.login.schemas import (
    ConsentInfoResponse,
    LoginInfoResponse,
    LoginResultResponse,
    RedirectToResponse,
    SentResponse,
)

from fastapi import APIRouter, Response, status

router = APIRouter(prefix="/v1/id", tags=["id-login"])

router.add_api_route(
    "/login", get_login, methods=["GET"], response_model=LoginInfoResponse
)
router.add_api_route(
    "/login", post_login, methods=["POST"], response_model=LoginResultResponse
)
router.add_api_route(
    "/login/otp/request",
    request_login_otp,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
    response_model=SentResponse,
)
router.add_api_route(
    "/login/otp", post_login_otp, methods=["POST"], response_model=LoginResultResponse
)
router.add_api_route(
    "/login/password",
    post_login_password,
    methods=["POST"],
    response_model=LoginResultResponse,
)
router.add_api_route(
    "/consent", get_consent, methods=["GET"], response_model=ConsentInfoResponse
)
router.add_api_route(
    "/consent", post_consent, methods=["POST"], response_model=RedirectToResponse
)
router.add_api_route(
    "/consent/otp",
    post_consent_otp,
    methods=["POST"],
    status_code=status.HTTP_202_ACCEPTED,
    response_class=Response,
)
router.add_api_route(
    "/logout", get_logout, methods=["GET"], response_model=RedirectToResponse
)
