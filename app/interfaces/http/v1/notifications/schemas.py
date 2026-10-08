"""Request and response models of the notification center."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel


class NotificationItemResponse(BaseModel):
    """One notification in the web center (NotificationItem)."""

    id: UUID
    type: str
    title: str
    body: str
    link: str | None
    created_at: datetime
    read_at: datetime | None


class UnreadCountResponse(BaseModel):
    """Number of unread notifications."""

    count: int
