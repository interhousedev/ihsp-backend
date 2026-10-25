"""The student's group curriculum from EMIS."""

from app.interfaces.http.v1.me_curriculum.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
