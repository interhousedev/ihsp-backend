"""Administration work-off routes (WO-8)."""

from app.interfaces.http.v1.admin_work_offs.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
