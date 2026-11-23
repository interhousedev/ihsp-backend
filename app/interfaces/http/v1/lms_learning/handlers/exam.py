"""Exam routes of the learner player: sitting, start module, answers, submit."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.interfaces.http.v1.lms_learning.schemas import (
    LearningExamAnswersBody,
    LearningExamSubmitBody,
)
from app.modules.lms.application.learning.views import LearningExamSessionView
from app.shared.actor import Actor

from fastapi import Depends, Response


async def get_exam_session(
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningExamSessionView:
    """Return my sitting; a module whose time ran out is closed on the way."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningExamSessionView = await container.lms.learning.exam_get.execute(
        actor, step_id, block_id
    )
    return view


async def start_exam_module(
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningExamSessionView:
    """Begin the next module (or return the open one) with its questions."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    view: LearningExamSessionView = await container.lms.learning.exam_start.execute(
        actor, step_id, block_id
    )
    return view


async def save_exam_answers(
    step_id: UUID,
    block_id: str,
    body: LearningExamAnswersBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningExamSessionView:
    """Merge answers into the open module (until its deadline plus 30 seconds)."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    answers = {
        question_id: answer.model_dump(exclude_none=True)
        for question_id, answer in body.answers.items()
    }
    learning = container.lms.learning
    view: LearningExamSessionView = await learning.exam_answers.execute(
        actor, step_id, block_id, body.module_id, answers
    )
    return view


async def submit_exam_module(
    step_id: UUID,
    block_id: str,
    body: LearningExamSubmitBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> LearningExamSessionView:
    """Submit the open module; the last one finishes and grades the exam."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    learning = container.lms.learning
    view: LearningExamSessionView = await learning.exam_submit.execute(
        actor, step_id, block_id, body.module_id
    )
    return view
