"""Administration logs: error issues read from the Bugsink server."""

from app.interfaces.http.v1.admin_logs.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
