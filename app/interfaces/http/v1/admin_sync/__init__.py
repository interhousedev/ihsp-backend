"""EMIS sync monitor routes: run list and manual run."""

from app.interfaces.http.v1.admin_sync.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
