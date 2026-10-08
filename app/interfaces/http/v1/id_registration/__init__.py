"""Registration, reclaim, EMIS password and account deletion routes (task B2)."""

from app.interfaces.http.v1.id_registration.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
