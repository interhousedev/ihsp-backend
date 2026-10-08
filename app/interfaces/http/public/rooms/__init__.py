"""Room pages (`ihsu.uz/r/{room}`)."""

from app.interfaces.http.public.rooms.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
