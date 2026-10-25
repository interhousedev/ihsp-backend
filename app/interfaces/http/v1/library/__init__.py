"""Library routes (`/v1/library/*`, `/v1/me/library/*`, `/v1/manage/library/*`, ...).

One package per area; the order matters only inside an area (fixed paths before
`/{id}` paths).
"""

from app.interfaces.http.v1.library import (
    catalogue,
    external,
    materials,
    reader,
    taxonomy,
)

from fastapi import APIRouter

ROUTERS: list[APIRouter] = [
    *catalogue.ROUTERS,
    *taxonomy.ROUTERS,
    *materials.ROUTERS,
    *reader.ROUTERS,
    *external.ROUTERS,
]
