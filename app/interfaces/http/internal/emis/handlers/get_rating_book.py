"""GET /internal/emis/{user_id}/rating-book."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisRatingBookResponse

from fastapi import Depends


async def get_rating_book(
    user_id: UUID, container: Annotated[Container, Depends(get_container)]
) -> EmisRatingBookResponse:
    """Have EMIS build the student's rating book and return its PDF address."""
    url = await container.identity.emis.gateway.rating_book(user_id)
    return EmisRatingBookResponse(url=url)
