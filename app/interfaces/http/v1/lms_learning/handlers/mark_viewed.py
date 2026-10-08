"""POST /v1/lms/steps/{step_id}/viewed: the student opened the step."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.modules.lms.application.learning.views import LearningStepProgressView
from app.shared.actor import Actor

from fastapi import Depends


async def mark_viewed(
    step_id: UUID,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningStepProgressView:
    """Record the view; a step without tests is completed by opening it."""
    view: LearningStepProgressView = (
        await container.lms.learning.mark_step_viewed.execute(actor, step_id)
    )
    return view
