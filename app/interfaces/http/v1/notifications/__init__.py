"""Notification center routes (WEB-27)."""

from app.interfaces.http.v1.notifications.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
