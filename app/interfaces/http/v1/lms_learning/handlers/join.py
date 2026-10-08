"""POST /v1/lms/join: join an invite-only course with its code."""

from typing import Annotated

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.schemas import LearningJoinBody
from app.modules.lms.application.learning.views import LearningCoursePageView
from app.shared.actor import Actor

from fastapi import Depends


async def join(
    body: LearningJoinBody,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningCoursePageView:
    """Join with an invite code (rate limited); a wrong code is a 404."""
    page: LearningCoursePageView = await container.lms.learning.join_course.execute(
        actor, body.code
    )
    return page
