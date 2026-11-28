"""Teacher AI routes; collected per process."""

from app.interfaces.http.v1.teacher_ai.question_bank import router as question_bank
from app.interfaces.http.v1.teacher_ai.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router, question_bank]
