"""GET /v1/lms/my-courses: enrolled and managed courses."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningMyCoursesView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def list_my_courses(
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningMyCoursesView:
    """Return the courses the caller studies and the courses they manage."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningMyCoursesView = await container.lms.learning.list_my_courses.execute(
        actor
    )
    return view
