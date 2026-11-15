"""Privacy: `/v1/me/privacy/*` (data export, erasure) and `/v1/admin/privacy/*`."""

from app.interfaces.http.v1.privacy.router import admin_router, mine

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [mine, admin_router]
