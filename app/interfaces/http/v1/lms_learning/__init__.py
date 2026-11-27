"""LMS learning routes (B13); I1 collects `ROUTERS` per process."""

from app.interfaces.http.v1.lms_learning.badge_authoring import (
    router as badge_authoring_router,
)
from app.interfaces.http.v1.lms_learning.badges import router as badges_router
from app.interfaces.http.v1.lms_learning.coach import router as coach_router
from app.interfaces.http.v1.lms_learning.levels import router as levels_router
from app.interfaces.http.v1.lms_learning.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    router,
    badges_router,
    coach_router,
    levels_router,
    badge_authoring_router,
]
