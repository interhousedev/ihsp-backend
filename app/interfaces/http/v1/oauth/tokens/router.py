"""Routes of the token handler."""

from app.interfaces.http.v1.oauth.tokens.handlers.post_logout import post_logout
from app.interfaces.http.v1.oauth.tokens.handlers.post_refresh import post_refresh
from app.interfaces.http.v1.oauth.tokens.handlers.post_telegram_token import (
    post_telegram_token,
)
from app.interfaces.http.v1.oauth.tokens.handlers.post_token import post_token
from app.interfaces.http.v1.oauth.tokens.schemas import LogoutResponse, TokenResponse

from fastapi import APIRouter

router = APIRouter(prefix="/v1/oauth", tags=["oauth"])

router.add_api_route(
    "/token", post_token, methods=["POST"], response_model=TokenResponse
)
router.add_api_route(
    "/refresh", post_refresh, methods=["POST"], response_model=TokenResponse
)
router.add_api_route(
    "/logout", post_logout, methods=["POST"], response_model=LogoutResponse
)
router.add_api_route(
    "/telegram", post_telegram_token, methods=["POST"], response_model=TokenResponse
)
