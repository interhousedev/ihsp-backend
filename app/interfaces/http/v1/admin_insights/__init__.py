"""Administration insights: system health, usage and marks for the report pages."""

from app.interfaces.http.v1.admin_insights.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
