"""Broadcast routes for Administration (ADM-11)."""

from app.interfaces.http.v1.admin_broadcasts.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
