"""Request and response models of outbound email."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class SendOutboundRequest(BaseModel):
    """`SendOutboundMail`: an email composed in the dialog."""

    to: list[str] = Field(min_length=1, max_length=20)
    subject: str = Field(min_length=1, max_length=200)
    body: str = Field(min_length=1, max_length=20000)
    attachment_file_id: UUID | None = None


class SendOutboundResponse(BaseModel):
    """`OutboundMailSent`: what was sent."""

    message_id: str
    to: list[str]
    attachment_name: str | None


class SentMailItemOut(BaseModel):
    """`SentMailItem`: one email the user sent."""

    id: UUID
    to: list[str]
    subject: str
    snippet: str
    sent_at: datetime
    status: str
    attachment_name: str | None


class SentMailPageOut(BaseModel):
    """`SentMailPage`: sent emails; `next_before` is the `before` of the next page."""

    items: list[SentMailItemOut]
    next_before: datetime | None
