"""Platform settings routes for Administration."""

from app.interfaces.http.v1.admin_settings.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
