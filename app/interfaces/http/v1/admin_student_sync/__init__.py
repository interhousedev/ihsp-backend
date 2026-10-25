"""Administrator EMIS sync of one student: queue it and read its status."""

from app.interfaces.http.v1.admin_student_sync.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
