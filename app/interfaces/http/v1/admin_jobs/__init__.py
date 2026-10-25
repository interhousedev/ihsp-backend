"""Admin process list: running and queued worker jobs, and stopping one."""

from app.interfaces.http.v1.admin_jobs.router import router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [router]
