"""The caller's own profile photo (/v1/me/photo; /v1/staff/me/photo is deprecated)."""

from app.interfaces.http.v1.me_photo.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
