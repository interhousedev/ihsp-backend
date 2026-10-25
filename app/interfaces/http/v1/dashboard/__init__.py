"""Dashboard routes: GET/PUT /v1/me/dashboard."""

from app.interfaces.http.v1.dashboard.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
