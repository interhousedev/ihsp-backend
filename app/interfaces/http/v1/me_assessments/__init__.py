"""Student exam calendar: /v1/me/assessments."""

from app.interfaces.http.v1.me_assessments.router import (
    periods_router,
    router,
)

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router, periods_router]
