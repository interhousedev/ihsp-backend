"""GET /internal/emis/{user_id}/profile."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisProfileResponse

from fastapi import Depends


async def get_profile(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> EmisProfileResponse:
    """Return the student's EMIS profile."""
    profile = await container.identity.emis.gateway.profile(user_id)
    return EmisProfileResponse.from_contract(profile)
