"""Release numbers of the installed app (PWA-3)."""

from app.interfaces.http.v1.app_version.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
