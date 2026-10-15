"""Tool calls stored with assistant messages (spec → Models → ChatMessage)."""

from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class ToolAccess(StrEnum):
    """Read tools run at once; write tools wait for approval."""

    READ = "read"
    WRITE = "write"


class ToolStatus(StrEnum):
    """Lifecycle of one tool call."""

    RUNNING = "running"
    PENDING_APPROVAL = "pending_approval"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    DONE = "done"
    FAILED = "failed"


class PreviewField(BaseModel):
    """One labelled value of an approval card (label is an i18n key)."""

    label_key: str
    value: str
    sensitive: bool = False


class PreviewData(BaseModel):
    """What an approval card shows, built by the server from the real arguments."""

    title_key: str
    title_params: dict[str, Any] = Field(default_factory=dict)
    fields: list[PreviewField] = Field(default_factory=list)
    items: list[str] = Field(default_factory=list)


class ToolCall(BaseModel):
    """A tool call of the model with its approval state and result."""

    id: str
    tool: str
    access: ToolAccess
    round: int = 0  # the model request of the answer that made the call
    args: dict[str, Any] = Field(default_factory=dict)
    status: ToolStatus
    preview: PreviewData | None = None
    expires_at: datetime | None = None
    decided_by: UUID | None = None
    decided_at: datetime | None = None
    reject_reason: str | None = None
    result: dict[str, Any] | None = None
    error: str | None = None

    def is_overdue(self, now: datetime) -> bool:
        """Return True if a pending approval is past its expiry."""
        return (
            self.status is ToolStatus.PENDING_APPROVAL
            and self.expires_at is not None
            and self.expires_at <= now
        )
