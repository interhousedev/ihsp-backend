"""Request and response models of outbound email."""

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
