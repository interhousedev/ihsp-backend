"""GET /v1/me/alerts."""

from typing import Annotated

from app.interfaces.http.dependencies import require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_alerts(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    composition: Annotated[Composition, Depends(get_composition)],
) -> list[JsonObject]:
    """Return what needs the student's attention on the Today page."""
    return await composition.build_alerts.execute(actor)
