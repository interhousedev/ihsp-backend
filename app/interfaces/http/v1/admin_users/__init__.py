"""Administration of users, teachers, audit and OAuth clients (/v1/admin/*)."""

from app.interfaces.http.v1.admin_users.audit.router import router as audit_router
from app.interfaces.http.v1.admin_users.oauth_clients.router import (
    router as oauth_clients_router,
)
from app.interfaces.http.v1.admin_users.teachers.router import router as teachers_router
from app.interfaces.http.v1.admin_users.users.router import router as users_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    users_router,
    teachers_router,
    audit_router,
    oauth_clients_router,
]
