"""GET /v1/lms/courses: the catalog of published public courses."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_CACHE
from app.modules.lms.application.learning.views import LearningCourseCardView
from app.shared.actor import Actor

from fastapi import Depends, Query, Response


async def list_courses(
    response: Response,
    _actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    query: Annotated[str | None, Query(max_length=100)] = None,
) -> list[LearningCourseCardView]:
    """List published public courses, optionally filtered by title."""
    response.headers["Cache-Control"] = PRIVATE_CACHE
    cards: list[LearningCourseCardView] = (
        await container.lms.learning.list_catalog.execute(query=query)
    )
    return cards
