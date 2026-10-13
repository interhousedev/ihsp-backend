"""Chat and message entities."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.chat_scope import ChatScope
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus
from app.shared.agent_steps import AgentStep
from app.shared.contracts.web_search import WebResult

from pydantic import BaseModel, Field

TITLE_MAX_CHARS = 60
APPROVAL_TTL_HOURS = 24


class MessageRole(StrEnum):
    """Who wrote a message."""

    USER = "user"
    ASSISTANT = "assistant"


class ChatTier(StrEnum):
    """The model class of a chat: `smart` is bigger and counts more in the budget."""

    FAST = "fast"
    SMART = "smart"


class Feedback(StrEnum):
    """A thumbs up or down on an assistant message."""

    UP = "up"
    DOWN = "down"


class Attachment(BaseModel):
    """A file attached to a user message."""

    file_id: UUID
    name: str


class MessageContent(BaseModel):
    """The jsonb `content` of a message: the text, the attached files and web results.

    `web` holds the pages of the web search a user message was sent with; the assistant
    messages of that turn carry the same pages, with `cited` set for those the answer
    uses (its text has ``⟦w1⟧`` chips for them).
    """

    text: str = ""
    attachments: list[Attachment] = Field(default_factory=list)
    web: list[WebResult] = Field(default_factory=list)
    # What the assistant did while answering (AI-STEPS); shown, never sent back.
    steps: list[AgentStep] = Field(default_factory=list)


@dataclass(slots=True)
class Chat:
    """A saved conversation with one assistant."""

    id: UUID
    owner_id: UUID
    assistant: Assistant
    title: str
    model: str
    last_message_at: datetime
    pending_approvals: int = 0
    deleted_at: datetime | None = None
    tier: ChatTier = ChatTier.FAST
    scope: ChatScope | None = None  # author chats: the course and its workspace

    @property
    def course_id(self) -> UUID | None:
        """The course of an author chat, None for the other assistants."""
        return self.scope.course_id if self.scope is not None else None


@dataclass(slots=True)
class ChatMessage:
    """One message; assistant messages carry the tool calls of one model request."""

    id: UUID
    chat_id: UUID
    seq: int
    role: MessageRole
    content: MessageContent
    created_at: datetime
    file_ids: list[UUID] = field(default_factory=list)
    tool_calls: list[ToolCall] = field(default_factory=list)
    tokens_in: int | None = None
    tokens_out: int | None = None
    feedback: Feedback | None = None
    feedback_comment: str | None = None

    @property
    def text(self) -> str:
        """Return the message text."""
        return self.content.text

    def find_call(self, call_id: str) -> ToolCall | None:
        """Return the tool call with this id."""
        return next((c for c in self.tool_calls if c.id == call_id), None)

    def pending_calls(self) -> list[ToolCall]:
        """Return the calls waiting for approval."""
        return [c for c in self.tool_calls if c.status is ToolStatus.PENDING_APPROVAL]


def title_from_text(text: str) -> str:
    """Return the automatic title: the first 60 characters of the first message."""
    flat = " ".join(text.split())
    return flat[:TITLE_MAX_CHARS]


def last_turn(
    messages: list[ChatMessage],
) -> tuple[ChatMessage, list[ChatMessage]] | None:
    """Return the last user message and the messages after it (the answer to redo)."""
    for index in range(len(messages) - 1, -1, -1):
        if messages[index].role is MessageRole.USER:
            return messages[index], messages[index + 1 :]
    return None


def count_pending(messages: list[ChatMessage]) -> int:
    """Return how many calls in the messages wait for approval."""
    return sum(len(m.pending_calls()) for m in messages)
