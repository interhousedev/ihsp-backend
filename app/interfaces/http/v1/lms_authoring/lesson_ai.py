"""Routes of the lesson AI: the step tutor (students) and video checks (authors)."""

from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from app.bootstrap.container import Container
from app.interfaces.http.dependencies import get_actor, get_container
from app.interfaces.http.v1.lms_learning.cache import PRIVATE_NO_STORE
from app.modules.lms.application.learning.ask_tutor import TutorConversation
from app.modules.lms.domain.learning.lesson_ai import (
    TRANSCRIPT_MAX_CHARS,
    TUTOR_MESSAGE_MAX_CHARS,
)
from app.shared.actor import Actor

from fastapi import APIRouter, Depends, Response
from pydantic import BaseModel, Field

Language = Literal["uz", "ru", "en"]
ActorDep = Annotated[Actor, Depends(get_actor)]
ContainerDep = Annotated[Container, Depends(get_container)]


class TutorMessageOut(BaseModel):
    """A message of the tutor conversation."""

    role: Literal["student", "tutor"]
    text: str
    created_at: datetime


class TutorConversationOut(BaseModel):
    """The conversation of the caller in the step."""

    messages: list[TutorMessageOut]
    remaining_today: int | None = Field(
        description="Questions left today; null for staff (no cap)."
    )


class TutorAskBody(BaseModel):
    """A question for the tutor."""

    message: str = Field(min_length=1, max_length=TUTOR_MESSAGE_MAX_CHARS)
    language: Language = "en"


def _out(conversation: TutorConversation) -> TutorConversationOut:
    return TutorConversationOut(
        messages=[
            TutorMessageOut(role=m.role, text=m.text, created_at=m.created_at)
            for m in conversation.messages
        ],
        remaining_today=conversation.remaining_today,
    )


async def get_tutor(
    step_id: UUID, response: Response, actor: ActorDep, container: ContainerDep
) -> TutorConversationOut:
    """Return the caller's tutor conversation in a live step."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    return _out(await container.lms_lesson_ai.ask_tutor.conversation(actor, step_id))


async def ask_tutor(
    step_id: UUID,
    body: TutorAskBody,
    response: Response,
    actor: ActorDep,
    container: ContainerDep,
) -> TutorConversationOut:
    """Ask the Socratic tutor about the step; it hints and never gives answers."""
    response.headers["Cache-Control"] = PRIVATE_NO_STORE
    conversation = await container.lms_lesson_ai.ask_tutor.ask(
        actor, step_id, body.message, body.language
    )
    return _out(conversation)


class VideoChecksBody(BaseModel):
    """The transcript of the video (plain text, lines may start with mm:ss)."""

    transcript: str = Field(min_length=1, max_length=TRANSCRIPT_MAX_CHARS)
    duration_seconds: float | None = Field(default=None, gt=0, le=36_000)
    language: Language = "en"
    title: str = Field(default="", max_length=300)


class VideoCheckOut(BaseModel):
    """A suggested pause-and-predict question."""

    at_seconds: float
    question: str
    options: list[str]
    correct_index: int
    explanation: str


class RecapCardOut(BaseModel):
    """A suggested recap flash card."""

    front: str
    back: str


class VideoChecksOut(BaseModel):
    """Suggestions the author edits before saving the draft."""

    checks: list[VideoCheckOut]
    cards: list[RecapCardOut]


async def suggest_video_checks(
    course_id: UUID,
    step_id: UUID,
    block_id: str,
    body: VideoChecksBody,
    actor: ActorDep,
    container: ContainerDep,
) -> VideoChecksOut:
    """Suggest checks every 2-3 minutes and recap cards; nothing is saved."""
    del block_id  # the block may exist only in the editor; the editor inserts
    result = await container.lms_lesson_ai.suggest_video_checks.execute(
        actor,
        course_id,
        step_id,
        transcript=body.transcript,
        duration_sec=body.duration_seconds,
        language=body.language,
        title=body.title,
    )
    return VideoChecksOut(
        checks=[
            VideoCheckOut(
                at_seconds=c.at_sec,
                question=c.question,
                options=c.options,
                correct_index=c.correct_index,
                explanation=c.explanation,
            )
            for c in result.checks
        ],
        cards=[RecapCardOut(front=f, back=b) for f, b in result.cards],
    )


router = APIRouter(prefix="/v1/lms", tags=["lms"])
router.add_api_route(
    "/steps/{step_id}/tutor",
    get_tutor,
    methods=["GET"],
    operation_id="lms_get_tutor",
)
router.add_api_route(
    "/steps/{step_id}/tutor",
    ask_tutor,
    methods=["POST"],
    operation_id="lms_ask_tutor",
)
router.add_api_route(
    "/courses/{course_id}/steps/{step_id}/blocks/{block_id}/video-checks/suggest",
    suggest_video_checks,
    methods=["POST"],
    operation_id="lms_suggest_video_checks",
    tags=["lms-authoring"],
)
