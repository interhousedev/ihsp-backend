"""GET /v1/lms/attempts/{id}: a graded attempt for its owner or a reviewer."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.views import LearningAttemptReviewView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def get_attempt(
    attempt_id: UUID,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningAttemptReviewView:
    """Return the attempt with variant and answers; correct answers per settings."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningAttemptReviewView = await container.lms.learning.get_attempt.execute(
        actor, attempt_id
    )
    return view
