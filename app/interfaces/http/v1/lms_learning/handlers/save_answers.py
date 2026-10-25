"""PUT /v1/lms/attempts/{id}/answers: save answers while the attempt is open."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import LearningSaveAnswersBody
from app.modules.lms.application.learning.views import LearningAttemptView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def save_answers(
    attempt_id: UUID,
    body: LearningSaveAnswersBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningAttemptView:
    """Merge the answers into the attempt."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    answers = {
        question_id: answer.model_dump(exclude_none=True)
        for question_id, answer in body.answers.items()
    }
    view: LearningAttemptView = await container.lms.learning.save_answers.execute(
        actor, attempt_id, answers
    )
    return view
