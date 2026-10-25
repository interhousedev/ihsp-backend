"""Route of Hydra's token hook."""

from app.interfaces.http.v1.oauth.token_hook.handlers.post_token_hook import (
    post_token_hook,
)

from fastapi import APIRouter

router = APIRouter(prefix="/v1/oauth", tags=["oauth"])

router.add_api_route("/token-hook", post_token_hook, methods=["POST"])
