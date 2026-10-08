"""JSON shapes of the public share endpoints."""

from datetime import datetime
from typing import Literal

from app.modules.links.application.views import PublicShareView

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """One message of a shared chat."""

    role: Literal["user", "assistant"]
    text: str
    tool_notes: list[str]


class SharedChat(BaseModel):
    """The messages of a shared chat."""

    messages: list[ChatMessage]


class SharedCard(BaseModel):
    """One card of a shared set."""

    id: str
    front: str
    back: str


class SharedCards(BaseModel):
    """The cards of a shared set."""

    cards: list[SharedCard]


class PublicShare(BaseModel):
    """What anyone with the share link sees."""

    kind: Literal["chat", "flashcard_set"]
    title: str
    author_first_name: str
    created_at: datetime
    chat: SharedChat | None
    flashcards: SharedCards | None


class ReportBody(BaseModel):
    """A visitor's report of a public page."""

    slug: str = Field(min_length=1, max_length=2200)
    reason: Literal["phishing", "malware", "personal_data", "offensive", "other"]
    comment: str | None = Field(default=None, max_length=500)


def public_share(view: PublicShareView) -> PublicShare:
    """Map a PublicShareView to its JSON shape."""
    chat = None
    if view.chat is not None:
        chat = SharedChat(
            messages=[
                ChatMessage(role=m.role, text=m.text, tool_notes=list(m.tool_notes))
                for m in view.chat
            ]
        )
    cards = None
    if view.flashcards is not None:
        cards = SharedCards(
            cards=[
                SharedCard(id=c.id, front=c.front, back=c.back) for c in view.flashcards
            ]
        )
    return PublicShare(
        kind=view.kind,
        title=view.title,
        author_first_name=view.author_first_name,
        created_at=view.created_at,
        chat=chat,
        flashcards=cards,
    )
