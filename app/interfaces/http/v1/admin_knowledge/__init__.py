"""Knowledge base admin routes (`/v1/admin/knowledge/*`)."""

from app.interfaces.http.v1.admin_knowledge.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
