"""AI assistant routes (task B9)."""

from app.interfaces.http.v1.ai.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
