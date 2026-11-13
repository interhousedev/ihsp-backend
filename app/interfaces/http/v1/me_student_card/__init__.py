"""The student's digital card (/v1/me/student-card)."""

from app.interfaces.http.v1.me_student_card.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
