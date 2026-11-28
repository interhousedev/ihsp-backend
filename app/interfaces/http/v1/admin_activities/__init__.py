"""Admin routes of clubs and the opportunities catalog (`/v1/admin/activities`)."""

from app.interfaces.http.v1.admin_activities.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
