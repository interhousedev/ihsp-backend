"""GET /v1/admin/dashboard."""

from typing import Annotated

from app.interfaces.http.dependencies import require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_dashboard(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    composition: Annotated[Composition, Depends(get_composition)],
) -> JsonObject:
    """Return the Administration dashboard."""
    return await composition.build_admin_dashboard.execute(actor)
