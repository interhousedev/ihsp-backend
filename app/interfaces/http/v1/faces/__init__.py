"""Face recognition routes: own face, staff upload, devices, entrance identify."""

from app.interfaces.http.v1.faces.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
