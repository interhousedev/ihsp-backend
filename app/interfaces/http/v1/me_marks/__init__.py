"""Student marks routes: subjects, grades, grades by day, record book."""

from app.interfaces.http.v1.me_marks.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
