"""Request and response models of the notebook chat (field names = § 4.4 contract)."""

from datetime import datetime
from typing import Any, Literal, Self
from uuid import UUID

from app.interfaces.http.v1.agent_steps import AgentStepResponse
from app.interfaces.http.v1.notebooks.schemas_common import NotebookUsageResponse
from app.interfaces.http.v1.web_search.schemas import WebResultResponse
from app.modules.notebooks.application.views import TurnView
from app.modules.notebooks.domain.entities import Anchor, Citation, NotebookMessage
from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.domain.limits import SOURCE_TITLE_MAX_CHARS
from app.shared.slash_commands import expand, stored_text

from pydantic import BaseModel, Field, model_validator

Rating = Literal["up", "down"]


class ChatAttachment(BaseModel):
    """A lesson, or one material of a lesson, the question is about (students).

    `lesson`: `id` is the lesson. `material`: `id` is the link of the material and
    `lesson_id` its lesson. The lesson's subject, date, topic, materials and homework
    reach the model as a pinned text.
    """

    kind: Literal["lesson", "material"]
    id: UUID
    lesson_id: UUID | None = None

    @model_validator(mode="after")
    def _material_needs_lesson(self) -> Self:
        if self.kind == "material" and self.lesson_id is None:
            raise ValueError("a material needs its lesson_id")
        return self


class SendMessageBody(BaseModel):
    """`POST /notebooks/{id}/chat/messages`.

    The 8 000 characters are a coarse cap on the payload; the question itself may
    have 4 000 characters after trimming (the use case answers 422 above that).
    """

    text: str = Field(default="", max_length=8000)
    command: str | None = Field(default=None, min_length=1, max_length=32)
    """A slash command (`cards`, `quiz`, ...) with its `args`: the question becomes the
    command's prompt (422 `ai/unknown-command` for an unknown name). Typed
    `/cards topic` in `text` works the same."""
    args: str = Field(default="", max_length=8000)
    source_ids: list[UUID] | None = Field(default=None, max_length=200)
    anchor: Anchor | None = None
    attachments: list[ChatAttachment] = Field(default_factory=list, max_length=5)
    """Lessons or lesson materials the question is about (see `ChatAttachment`)."""
    web_search: bool = False
    """Also search the web for this question: spends one of today's searches (404
    `web-search/disabled`, 429 `web-search/quota-exceeded`, 503
    `web-search/unavailable`;
    nothing is stored then). The pages come back in `web` and as the `web` event."""

    @model_validator(mode="after")
    def _needs_text_or_command(self) -> Self:
        if not self.text.strip() and not self.command:
            raise ValueError("text or command is required")
        return self

    def question(self) -> str:
        """The question to ask: the prompt of a slash command, else the text."""
        return expand(stored_text(self.command, self.args, self.text))


class FeedbackBody(BaseModel):
    """`POST /notebooks/{id}/chat/messages/{mid}/feedback`."""

    rating: Rating
    comment: str | None = Field(default=None, max_length=1000)


class SaveNoteBody(BaseModel):
    """`POST /notebooks/{id}/chat/messages/{mid}/save-note`."""

    title: str | None = Field(default=None, max_length=SOURCE_TITLE_MAX_CHARS)


def _rating_of(value: int | None) -> Rating | None:
    """The thumb as stored (1 up, -1 down) in the name the contract uses."""
    if value is None:
        return None
    return "up" if value > 0 else "down"


class NotebookMessageResponse(BaseModel):
    """`NotebookMessage`."""

    id: UUID
    seq: int
    role: MessageRole
    text: str
    citations: list[Citation]
    followups: list[str]
    source_ids: list[UUID]
    web: list[WebResultResponse]
    """Pages of the web search; `⟦w1⟧` chips in `text` point at them (`cited` ones)."""
    retrieval: bool
    grounded: bool
    feedback: Rating | None
    stopped: bool
    created_at: datetime
    steps: list[AgentStepResponse] = Field(default_factory=list)
    """What the assistant did while answering, in order (AI-STEPS)."""

    @classmethod
    def from_entity(cls, message: NotebookMessage) -> Self:
        """Build from the message entity."""
        content = message.content
        return cls(
            id=message.id,
            seq=message.seq,
            role=message.role,
            text=content.text,
            citations=list(content.citations),
            followups=list(content.followups),
            source_ids=list(content.source_ids),
            web=[WebResultResponse.from_result(item) for item in content.web],
            retrieval=content.retrieval,
            grounded=content.grounded,
            feedback=_rating_of(message.feedback),
            stopped=message.stopped,
            created_at=message.created_at,
            steps=[AgentStepResponse.model_validate(s) for s in content.steps],
        )


class ChatHistoryResponse(BaseModel):
    """`{messages}`: the last messages of the thread, oldest first."""

    messages: list[NotebookMessageResponse]

    @classmethod
    def from_entities(cls, messages: list[NotebookMessage]) -> Self:
        """Build from the message entities."""
        return cls(
            messages=[NotebookMessageResponse.from_entity(item) for item in messages]
        )


class NotebookTurnResponse(BaseModel):
    """`NotebookTurn`: both messages of one question, the usage, the proposed output."""

    user_message: NotebookMessageResponse
    assistant_message: NotebookMessageResponse
    usage: NotebookUsageResponse
    action: dict[str, Any] | None

    @classmethod
    def from_view(cls, view: TurnView) -> Self:
        """Build from the use case view."""
        return cls(
            user_message=NotebookMessageResponse.from_entity(view.user_message),
            assistant_message=NotebookMessageResponse.from_entity(
                view.assistant_message
            ),
            usage=NotebookUsageResponse.from_view(view.usage),
            action=view.action,
        )
