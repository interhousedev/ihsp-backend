"""POST /v1/lms/steps/{step_id}/blocks/{block_id}/attempts: start a test attempt."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningAttemptView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def start_attempt(
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
    preview: bool = False,
) -> LearningAttemptView:
    """Start an attempt (or resume the open one); `preview=true` is for staff."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningAttemptView = await container.lms.learning.start_attempt.execute(
        actor, step_id, block_id, preview=preview
    )
    return view
