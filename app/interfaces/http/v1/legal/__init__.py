"""Legal documents: `/v1/legal/*`, `/v1/me/legal/*`, `/v1/admin/legal/*`."""

from app.interfaces.http.v1.legal.router import admin_router, mine, public

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [public, mine, admin_router]
