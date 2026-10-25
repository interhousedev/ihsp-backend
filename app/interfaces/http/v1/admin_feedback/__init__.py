"""Platform feedback admin routes (`/v1/admin/feedback/*`)."""

from app.interfaces.http.v1.admin_feedback.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
