"""Staff subject group routes: a teacher's groups, students and their records."""

from app.interfaces.http.v1.staff_subjects.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
