"""POST /v1/lms/courses/{id or slug}/enroll: enroll in a public course."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.shared.actor import Actor

from fastapi import Depends


async def enroll(
    course_id: str,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningCoursePageView:
    """Enroll the caller and return the course page."""
    page: LearningCoursePageView = (
        await container.lms.learning.enroll_in_course.execute(actor, course_id)
    )
    return page
