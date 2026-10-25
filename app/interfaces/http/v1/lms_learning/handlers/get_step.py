"""GET /v1/lms/courses/{id}/steps/{step_id}: a step as a student sees it."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_CACHE
from app.modules.lms.application.learning.views import LearningStepView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def get_step(
    course_id: UUID,
    step_id: UUID,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningStepView:
    """Return the live step without correct answers, with the caller's state."""
    response.headers["Cache-Control"] = PRIVATE_CACHE
    view: LearningStepView = await container.lms.learning.get_step_view.execute(
        actor, course_id, step_id
    )
    return view
