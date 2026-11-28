"""Clubs, events, team, points and opportunities for students and club staff."""

from app.interfaces.http.v1.activities.clubs import router as clubs_router
from app.interfaces.http.v1.activities.engagement import router as engagement_router
from app.interfaces.http.v1.activities.events import router as events_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [clubs_router, events_router, engagement_router]
