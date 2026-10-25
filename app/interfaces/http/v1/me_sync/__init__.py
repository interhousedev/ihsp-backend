"""The student's own full EMIS sync (the settings button)."""

from app.interfaces.http.v1.me_sync.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
