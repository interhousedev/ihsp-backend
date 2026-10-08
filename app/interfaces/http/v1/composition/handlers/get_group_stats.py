"""GET /v1/admin/groups/stats."""

from typing import Annotated

from app.interfaces.http.dependencies import require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_group_stats(
    actor: Annotated[Actor, Depends(require_roles(Role.ADMIN))],
    composition: Annotated[Composition, Depends(get_composition)],
) -> list[JsonObject]:
    """Return the attendance rate and the average GPA of every active group."""
    return await composition.build_group_stats.execute(actor)
