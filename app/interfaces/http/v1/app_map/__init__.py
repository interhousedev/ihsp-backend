"""The map of app pages for the signed-in user."""

from app.interfaces.http.v1.app_map.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
