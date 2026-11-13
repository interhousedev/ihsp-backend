"""The public client configuration (/v1/public/client-config)."""

from app.interfaces.http.v1.public_config.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
