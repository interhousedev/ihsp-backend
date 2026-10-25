"""The broadcast entity and its lifecycle from draft to sent."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from app.modules.admin.domain.audience import Audience
from app.modules.admin.domain.errors import (
    BroadcastNotCancellableError,
    BroadcastNotEditableError,
    BroadcastNotSendableError,
)


class BroadcastStatus(StrEnum):
    """Lifecycle state of a broadcast."""

    DRAFT = "draft"
    SCHEDULED = "scheduled"
    SENDING = "sending"
    SENT = "sent"
    CANCELLED = "cancelled"


class CreatedVia(StrEnum):
    """Where the draft came from; the assistant can only create drafts."""

    UI = "ui"
    ASSISTANT = "assistant"


@dataclass(frozen=True, slots=True)
class BroadcastStats:
    """Delivery counts, frozen when sending finishes."""

    total: int
    sent: int
    failed: int
    blocked: int


@dataclass(slots=True)
class Broadcast:
    """A message to many users written by Administration."""

    id: UUID
    author_id: UUID
    created_via: CreatedVia
    title: str
    text: str
    audience: Audience
    created_at: datetime
    media_file_ids: list[UUID] = field(default_factory=list)
    scheduled_at: datetime | None = None
    status: BroadcastStatus = BroadcastStatus.DRAFT
    stats: BroadcastStats | None = None

    def ensure_editable(self) -> None:
        """Only drafts and scheduled broadcasts can change."""
        if self.status not in (BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED):
            raise BroadcastNotEditableError(params={"status": self.status.value})

    def ensure_sendable(self) -> None:
        """Only drafts and scheduled broadcasts can be sent."""
        if self.status not in (BroadcastStatus.DRAFT, BroadcastStatus.SCHEDULED):
            raise BroadcastNotSendableError(params={"status": self.status.value})

    def schedule(self, at: datetime) -> None:
        """Wait until `at` before sending."""
        self.ensure_sendable()
        self.status = BroadcastStatus.SCHEDULED
        self.scheduled_at = at

    def start_sending(self, recipients: int) -> None:
        """Begin delivery; `stats.total` remembers how many notifications to expect."""
        self.ensure_sendable()
        self.status = BroadcastStatus.SENDING
        self.stats = BroadcastStats(total=recipients, sent=0, failed=0, blocked=0)

    def cancel(self) -> None:
        """Cancel a scheduled broadcast."""
        if self.status != BroadcastStatus.SCHEDULED:
            raise BroadcastNotCancellableError(params={"status": self.status.value})
        self.status = BroadcastStatus.CANCELLED

    def finish(self, stats: BroadcastStats) -> None:
        """Freeze the delivery counts."""
        self.status = BroadcastStatus.SENT
        self.stats = stats

    def notification_payload(self, *, preview: bool = False) -> dict[str, Any]:
        """Snapshot of what recipients get; renderers and the web center read it."""
        payload: dict[str, Any] = {
            "broadcast_id": str(self.id),
            "title": self.title,
            "text": self.text,
            "media_file_ids": [str(file_id) for file_id in self.media_file_ids],
        }
        if preview:
            payload["preview"] = True
        return payload
