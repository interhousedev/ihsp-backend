"""Staff work-off template and work-off routes (WO-1, WO-3)."""

from app.interfaces.http.v1.staff_work_offs.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
