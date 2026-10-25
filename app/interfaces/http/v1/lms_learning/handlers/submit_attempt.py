"""POST /v1/lms/attempts/{id}/submit: submit and grade an attempt."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningAttemptResultView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def submit_attempt(
    attempt_id: UUID,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningAttemptResultView:
    """Grade the attempt on the server; answers are shown as the test allows."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    result: LearningAttemptResultView = (
        await container.lms.learning.submit_attempt.execute(actor, attempt_id)
    )
    return result
