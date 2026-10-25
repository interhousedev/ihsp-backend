"""Internal EMIS gateway routes (task B2)."""

from app.interfaces.http.internal.emis.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
