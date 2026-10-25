"""POST /v1/lms/attempts/{id}/override: override the score of an attempt."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import LearningOverrideScoreBody
from app.modules.lms.application.learning.views import LearningAttemptReviewView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def override_attempt(
    attempt_id: UUID,
    body: LearningOverrideScoreBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningAttemptReviewView:
    """Set the score and a comment; `passed`, completion and progress follow."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningAttemptReviewView = (
        await container.lms.learning.override_score.execute(
            actor, attempt_id, body.score, body.comment
        )
    )
    return view
