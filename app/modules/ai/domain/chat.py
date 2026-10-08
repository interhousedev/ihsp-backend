"""Chat and message entities."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from app.modules.ai.domain.assistant import Assistant
from app.modules.ai.domain.tool_call import ToolCall, ToolStatus

from pydantic import BaseModel, Field

TITLE_MAX_CHARS = 60
APPROVAL_TTL_HOURS = 24


class MessageRole(StrEnum):
    """Who wrote a message."""

    USER = "user"
    ASSISTANT = "assistant"


class Attachment(BaseModel):
    """A file attached to a user message."""

    file_id: UUID
    name: str


class MessageContent(BaseModel):
    """The jsonb `content` of a message: the text and the attached files."""

    text: str = ""
    attachments: list[Attachment] = Field(default_factory=list)


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


def count_pending(messages: list[ChatMessage]) -> int:
    """Return how many calls in the messages wait for approval."""
    return sum(len(m.pending_calls()) for m in messages)
