"""The staff member's own profile photo (/v1/staff/me/photo)."""

from app.interfaces.http.v1.me_photo.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
