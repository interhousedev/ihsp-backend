"""Student profile and timetable routes, and the staff timetable (B3)."""

from app.interfaces.http.v1.me_schedule.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
