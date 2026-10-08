"""GET /internal/emis/{user_id}/timetable."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisTimetableItemResponse

from fastapi import Depends


async def get_timetable(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> list[EmisTimetableItemResponse]:
    """Return the weekly timetable of the student's group."""
    items = await container.identity.emis.gateway.timetable(user_id)
    return [EmisTimetableItemResponse.from_contract(item) for item in items]
