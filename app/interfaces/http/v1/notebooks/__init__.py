"""Notebook routes (`/v1/notebooks/*`, § 4.3).

The order matters: `GET /notebooks/usage` and `POST .../sources/select` are
registered before the routes with a path parameter.
"""

from app.interfaces.http.v1.notebooks.router_admin_materials import (
    router as admin_materials_router,
)
from app.interfaces.http.v1.notebooks.router_chat import router as chat_router
from app.interfaces.http.v1.notebooks.router_labels import router as labels_router
from app.interfaces.http.v1.notebooks.router_notebooks import router as notebooks_router
from app.interfaces.http.v1.notebooks.router_sources import router as sources_router
from app.interfaces.http.v1.notebooks.router_staff_subjects import (
    router as staff_subjects_router,
)
from app.interfaces.http.v1.notebooks.router_studio import router as studio_router

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    notebooks_router,
    sources_router,
    labels_router,
    chat_router,
    studio_router,
    admin_materials_router,
    staff_subjects_router,
]
