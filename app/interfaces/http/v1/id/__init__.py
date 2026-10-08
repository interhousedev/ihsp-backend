"""Identity routes under /v1/id/* (login app, account, recovery, connectors)."""

from app.interfaces.http.v1.id.account.router import router as account_router
from app.interfaces.http.v1.id.activation.router import router as activation_router
from app.interfaces.http.v1.id.connectors.router import router as connectors_router
from app.interfaces.http.v1.id.login.router import router as login_router
from app.interfaces.http.v1.id.recovery.router import router as recovery_router
from app.interfaces.http.v1.id.telegram.router import router as telegram_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    login_router,
    telegram_router,
    recovery_router,
    activation_router,
    account_router,
    connectors_router,
]
