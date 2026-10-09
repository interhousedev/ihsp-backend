"""Routes of the library materials area: uploads, queue, reports, sanctions."""

from app.interfaces.http.v1.library.materials.router_admin import router as admin
from app.interfaces.http.v1.library.materials.router_manage import router as manage
from app.interfaces.http.v1.library.materials.router_materials import (
    router as materials,
)

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [materials, manage, admin]
