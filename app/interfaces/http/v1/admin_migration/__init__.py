"""Server migration routes for Administration."""

from app.interfaces.http.v1.admin_migration.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
