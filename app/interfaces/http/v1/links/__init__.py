"""HTTP routes of links, shares, lesson resources and public share pages."""

from app.interfaces.http.v1.links.lesson_resources.router import (
    router as lesson_resources_router,
)
from app.interfaces.http.v1.links.lesson_sources.router import (
    router as lesson_sources_router,
)
from app.interfaces.http.v1.links.links.router import router as links_router
from app.interfaces.http.v1.links.public_shares.router import (
    router as public_shares_router,
)
from app.interfaces.http.v1.links.shares.router import router as shares_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    links_router,
    shares_router,
    lesson_resources_router,
    lesson_sources_router,
    public_shares_router,
]
