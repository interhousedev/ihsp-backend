"""Composition endpoints: alerts, search, calendar token, admin dashboard and 360 views.

Wiring: `wiring.composition_from_container` + `wiring.install_composition`.
"""

from app.interfaces.http.v1.composition.admin_router import router as admin_router
from app.interfaces.http.v1.composition.me_router import router as me_router

from fastapi import APIRouter

# Include these before the routers of `admin_schedule`: `/v1/admin/groups/stats` must
# win against `/v1/admin/groups/{id}`.
ROUTERS: list[APIRouter] = [me_router, admin_router]
