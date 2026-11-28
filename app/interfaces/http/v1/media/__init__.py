"""Media job routes: one job voices a script and optionally renders the video."""

from app.interfaces.http.v1.media.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
