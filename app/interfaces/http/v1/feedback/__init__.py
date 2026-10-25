"""Platform feedback routes of signed-in users (`/v1/feedback/*`)."""

from app.interfaces.http.v1.feedback.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
