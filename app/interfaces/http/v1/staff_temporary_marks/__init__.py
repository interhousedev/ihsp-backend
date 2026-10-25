"""Staff temporary gradebook routes (TMP-1, TMP-3)."""

from app.interfaces.http.v1.staff_temporary_marks.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
