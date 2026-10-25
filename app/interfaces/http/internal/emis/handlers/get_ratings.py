"""GET /internal/emis/{user_id}/ratings?subject=&semester=."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container
from app.interfaces.http.internal.emis.schemas import EmisSubjectRatingsResponse

from fastapi import Depends, Query


async def get_ratings(
    user_id: UUID,
    subject: Annotated[int, Query(ge=1)],
    semester: Annotated[int, Query(ge=1, le=8)],
    container: Annotated[Container, Depends(get_container)],
) -> EmisSubjectRatingsResponse:
    """Return the marks and the semester rating of one subject."""
    ratings = await container.identity.emis.gateway.ratings(user_id, subject, semester)
    return EmisSubjectRatingsResponse.from_contract(ratings)
