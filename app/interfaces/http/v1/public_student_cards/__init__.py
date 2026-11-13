"""The public view of a shared student card (/v1/public/student-cards)."""

from app.interfaces.http.v1.public_student_cards.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
