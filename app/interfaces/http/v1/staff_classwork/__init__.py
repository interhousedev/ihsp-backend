"""Staff classwork routes (B4)."""

from app.interfaces.http.v1.staff_classwork.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
