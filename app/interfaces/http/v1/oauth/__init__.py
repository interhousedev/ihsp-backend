"""Token handler, token hook and Hydra's login, consent, logout URLs: /v1/oauth/*."""

from app.interfaces.http.v1.oauth.flow.router import router as flow_router
from app.interfaces.http.v1.oauth.mcp_redirect_sync import (
    router as mcp_redirect_sync_router,
)
from app.interfaces.http.v1.oauth.mcp_register import router as mcp_register_router
from app.interfaces.http.v1.oauth.token_hook.router import router as hook_router
from app.interfaces.http.v1.oauth.tokens.router import router as tokens_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    tokens_router,
    hook_router,
    flow_router,
    mcp_register_router,
    mcp_redirect_sync_router,
]
