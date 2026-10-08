"""Student classwork routes (B4)."""

from app.interfaces.http.v1.me_classwork.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
