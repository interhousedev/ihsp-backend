"""robots.txt of the public hosts."""

from app.interfaces.http.public.robots.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
