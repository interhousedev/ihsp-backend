"""Token handler and Hydra token hook under /v1/oauth/*."""

from app.interfaces.http.v1.oauth.token_hook.router import router as hook_router
from app.interfaces.http.v1.oauth.tokens.router import router as tokens_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [tokens_router, hook_router]
