"""GET /internal/emis/{user_id}/class-hours."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisClassHourResponse

from fastapi import Depends


async def get_class_hours(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> list[EmisClassHourResponse]:
    """Return the bells of the lyceum as EMIS lists them."""
    hours = await container.identity.emis.gateway.class_hours(user_id)
    return [EmisClassHourResponse.from_contract(hour) for hour in hours]
