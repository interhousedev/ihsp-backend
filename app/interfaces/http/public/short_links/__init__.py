"""Short link pages: `ROUTERS` for the dev app, `HOST_ROUTERS` for host s.ihsu.uz."""

from app.interfaces.http.public.short_links.router import host_router, router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
HOST_ROUTERS: list[APIRouter] = [host_router]
