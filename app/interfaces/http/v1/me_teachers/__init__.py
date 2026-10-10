"""My teachers (student) and teacher contacts (staff, admin)."""

from app.interfaces.http.v1.me_teachers.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
