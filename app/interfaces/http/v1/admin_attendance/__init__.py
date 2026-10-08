"""Admin attendance routes (B4)."""

from app.interfaces.http.v1.admin_attendance.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
