"""GET /v1/lms/courses/{slug}: the course page."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_CACHE
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def get_course(
    slug: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningCoursePageView:
    """Show the course: description, staff, outline and the caller's progress."""
    response.headers["Cache-Control"] = PRIVATE_CACHE
    page: LearningCoursePageView = await container.lms.learning.get_course_page.execute(
        actor, slug
    )
    return page
