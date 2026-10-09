"""Routes of the library external area (UniLibrary records and their administration)."""

from app.interfaces.http.v1.library.external.router_admin import router as admin_router
from app.interfaces.http.v1.library.external.router_unilibrary import (
    router as unilibrary_router,
)

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [unilibrary_router, admin_router]
