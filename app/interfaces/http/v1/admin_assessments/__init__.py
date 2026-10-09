"""Administration controls: /v1/admin/assessments."""

from app.interfaces.http.v1.admin_assessments.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
