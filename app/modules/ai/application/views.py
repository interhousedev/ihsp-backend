"""Localized read models returned by the use cases (shaped like the API schemas)."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Literal
from uuid import UUID

from app.modules.ai.application.budget import UsageInfo
from app.shared.contracts.web_search import WebResult


class TurnStatus(StrEnum):
    """How a turn ended."""

    DONE = "done"
    AWAITING_APPROVAL = "awaiting_approval"
    LIMIT_REACHED = "limit_reached"


@dataclass(frozen=True, slots=True)
class ChatItemView:
    """One row of the chat list."""

    id: UUID
    assistant: Literal["student", "admin", "lms_author"]
    title: str
    last_message_at: datetime
    pending_approvals: int
    tier: Literal["fast", "smart"]
    course_id: UUID | None = None  # author chats: the course they belong to


@dataclass(frozen=True, slots=True)
class PreviewFieldView:
    """A labelled value of an approval card."""

    label: str
    value: str
    sensitive: bool


@dataclass(frozen=True, slots=True)
class PreviewView:
    """An approval card as shown to the user."""

    title: str
    fields: list[PreviewFieldView] = field(default_factory=list)
    items: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class DocumentCardView:
    """A document the assistant made: shown as a file card with a download."""

    file_id: UUID
    name: str
    kind: Literal["docx", "xlsx", "pptx"]
    size: int


@dataclass(frozen=True, slots=True)
class ToolCallView:
    """A tool call as shown in the chat."""

    id: str
    tool: str
    access: Literal["read", "write"]
    status: str
    note: str
    preview: PreviewView | None
    reject_reason: str | None
    expires_at: datetime | None
    document: DocumentCardView | None = None


@dataclass(frozen=True, slots=True)
class ChatMessageView:
    """A message with its tool calls."""

    seq: int
    role: Literal["user", "assistant"]
    text: str
    file_ids: list[UUID]
    tool_calls: list[ToolCallView]
    created_at: datetime
    feedback: Literal["up", "down"] | None
    web: list[WebResult] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ChatDetailView:
    """A chat with all messages."""

    chat: ChatItemView
    messages: list[ChatMessageView]
    shared: bool


@dataclass(frozen=True, slots=True)
class TurnResultView:
    """Result of sending a message or deciding an approval card.

    `new_messages` holds every message created or changed by the call, oldest
    first; clients replace messages with the same `seq`.
    """

    chat: ChatItemView
    new_messages: list[ChatMessageView]
    status: TurnStatus
    usage: UsageInfo
