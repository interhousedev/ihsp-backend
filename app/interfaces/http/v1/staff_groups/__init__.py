"""Staff group routes: groups a teacher curates (B3)."""

from app.interfaces.http.v1.staff_groups.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
