"""HTTP routes of Administration moderation."""

from app.interfaces.http.v1.admin_moderation.moderation.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
