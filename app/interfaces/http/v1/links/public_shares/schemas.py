"""JSON shapes of the public share endpoints."""

from datetime import datetime
from typing import Any, Literal

from app.modules.links.application.views import PublicShareView

from pydantic import BaseModel, ConfigDict, Field


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


class SharedArtifact(BaseModel):
    """A shared Studio output: its kind and the content the viewers render."""

    kind: str
    content: dict[str, Any]
    options: dict[str, Any]


class PublicShare(BaseModel):
    """What anyone with the share link sees."""

    kind: Literal["chat", "flashcard_set", "artifact"]
    title: str
    author_first_name: str
    created_at: datetime
    chat: SharedChat | None
    flashcards: SharedCards | None
    artifact: SharedArtifact | None = None


class PublicVisualization(BaseModel):
    """A shared answer with OpenUI blocks: nothing but its text and dates."""

    model_config = ConfigDict(extra="forbid")

    text: str
    created_at: datetime
    expires_at: datetime


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
        artifact=(
            SharedArtifact(
                kind=view.artifact.kind,
                content=view.artifact.content,
                options=view.artifact.options,
            )
            if view.artifact is not None
            else None
        ),
    )
