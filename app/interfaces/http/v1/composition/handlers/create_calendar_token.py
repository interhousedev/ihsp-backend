"""POST /v1/me/calendar-token."""

from typing import Annotated

from app.interfaces.http.dependencies import require_roles
from app.interfaces.http.v1.composition.dependencies import get_composition
from app.interfaces.http.v1.composition.services import Composition
from app.shared.actor import Actor, Role

from fastapi import Depends


async def create_calendar_token(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    composition: Annotated[Composition, Depends(get_composition)],
) -> dict[str, str]:
    """Create or rotate the secret iCal URL; the previous URL stops working."""
    url = await composition.issue_calendar_token.execute(actor)
    return {"url": url}
