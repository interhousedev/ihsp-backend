"""Staff portal controls: /v1/staff/assessments."""

from app.interfaces.http.v1.staff_assessments.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
