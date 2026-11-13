"""GET /v1/me/emis/rating-book."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_container, require_roles
from app.interfaces.http.v1.me_marks.schemas import RatingBookResponse
from app.shared.actor import Actor, Role

from fastapi import Depends


async def get_rating_book(
    actor: Annotated[Actor, Depends(require_roles(Role.STUDENT))],
    container: Annotated[Container, Depends(get_container)],
) -> RatingBookResponse:
    """Return the link to the student's EMIS rating book."""
    url = await container.academic.marks.get_rating_book.execute(actor)
    return RatingBookResponse(url=url)
