"""Routes of the AI review block: a student's review chat and the staff list."""

from typing import Annotated
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.ai_review import (
    AiReviewMessagesView,
    AiReviews,
    AiReviewSessionSummaryView,
    AiReviewSessionView,
    AiReviewSubmissionView,
)
from app.modules.lms.domain.learning.ai_review import MAX_FILES_PER_MESSAGE
from app.modules.lms.domain.learning.ai_review_errors import AiReviewUnavailableError
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/lms", tags=["lms"])

BLOCK = "/steps/{step_id}/blocks/{block_id}/ai-review/sessions"
SESSION = "/ai-review/sessions/{session_id}"


class AiReviewMessageBody(BaseModel):
    """A chat message with optional files uploaded with purpose `lms_ai_review`."""

    text: str = Field(default="", max_length=4000)
    file_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILES_PER_MESSAGE)


class AiReviewSubmitBody(BaseModel):
    """The work to review: files and a note."""

    file_ids: list[UUID] = Field(default_factory=list, max_length=MAX_FILES_PER_MESSAGE)
    note: str = Field(default="", max_length=4000)


class AiReviewSessionListView(BaseModel):
    """The student's conversations about one block."""

    items: list[AiReviewSessionSummaryView]


class AiReviewSubmissionListView(BaseModel):
    """Reviewed work of a block, for course staff."""

    items: list[AiReviewSubmissionView]


def _reviews(container: Container, response: Response) -> AiReviews:
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    reviews = container.lms.learning.ai_review
    if reviews is None:
        raise AiReviewUnavailableError()
    return reviews


async def lms_ai_review_create_session(
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewSessionView:
    """Start a new review conversation about the block."""
    return await _reviews(container, response).create_session(actor, step_id, block_id)


async def lms_ai_review_list_sessions(
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewSessionListView:
    """My review conversations about the block, newest first."""
    items = await _reviews(container, response).list_sessions(actor, step_id, block_id)
    return AiReviewSessionListView(items=items)


async def lms_ai_review_get_session(
    session_id: UUID,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewSessionView:
    """One of my review conversations with its messages."""
    return await _reviews(container, response).get_session(actor, session_id)


async def lms_ai_review_send_message(
    session_id: UUID,
    body: AiReviewMessageBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewMessagesView:
    """Send a message; the reviewer answers (or reviews after its questions)."""
    return await _reviews(container, response).send_message(
        actor, session_id, body.text, body.file_ids
    )


async def lms_ai_review_submit(
    session_id: UUID,
    body: AiReviewSubmitBody,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewMessagesView:
    """Submit work for review; spends one of the block's submissions."""
    return await _reviews(container, response).submit(
        actor, session_id, body.file_ids, body.note
    )


async def lms_ai_review_list_submissions(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    response: Response,
    actor: Annotated[Actor, Depends(get_actor)],
    container: Annotated[Container, Depends(get_container)],
) -> AiReviewSubmissionListView:
    """Course staff: the submitted work of the block with the latest reviews."""
    items = await _reviews(container, response).list_submissions(
        actor, course_id, step_id, block_id
    )
    return AiReviewSubmissionListView(items=items)


router.add_api_route(BLOCK, lms_ai_review_create_session, methods=["POST"])
router.add_api_route(BLOCK, lms_ai_review_list_sessions, methods=["GET"])
router.add_api_route(SESSION, lms_ai_review_get_session, methods=["GET"])
router.add_api_route(
    f"{SESSION}/messages", lms_ai_review_send_message, methods=["POST"]
)
router.add_api_route(f"{SESSION}/submit", lms_ai_review_submit, methods=["POST"])
router.add_api_route(
    "/courses/{course_id}/steps/{step_id}/blocks/{block_id}/ai-review/submissions",
    lms_ai_review_list_submissions,
    methods=["GET"],
)
