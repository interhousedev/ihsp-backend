"""Result objects returned by use cases (mapped to JSON by the interfaces)."""

from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import UUID

from app.modules.links.domain.link import Link
from app.shared.contracts.files import FileRef


@dataclass(frozen=True, slots=True)
class PersonView:
    """Id and names of a user (PersonRef)."""

    id: UUID
    first_name: str
    last_name: str


@dataclass(frozen=True, slots=True)
class LinkView:
    """A link with its public URL and file."""

    link: Link
    url: str
    file: FileRef | None = None


@dataclass(frozen=True, slots=True)
class LinkPage:
    """A page of the owner's links."""

    items: list[LinkView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ResourceView:
    """A lesson resource: link, display data, author and file."""

    link: Link
    short_url: str
    title: str
    author: PersonView
    file: FileRef | None


@dataclass(frozen=True, slots=True)
class ModerationView:
    """A link in the moderation queue with its owner."""

    link: LinkView
    owner: PersonView | None


@dataclass(frozen=True, slots=True)
class ModerationPage:
    """A page of the moderation queue."""

    items: list[ModerationView]
    next_cursor: str | None


@dataclass(frozen=True, slots=True)
class ChatShareView:
    """One message of a shared chat."""

    role: Literal["user", "assistant"]
    text: str
    tool_notes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class CardShareView:
    """One card of a shared flash card set."""

    id: str
    front: str
    back: str


@dataclass(frozen=True, slots=True)
class PublicShareView:
    """What anyone with a share link sees."""

    kind: Literal["chat", "flashcard_set"]
    title: str
    author_first_name: str
    created_at: datetime
    chat: tuple[ChatShareView, ...] | None
    flashcards: tuple[CardShareView, ...] | None


@dataclass(frozen=True, slots=True)
class WebResponse:
    """An HTTP answer of a public page: status, headers and body."""

    status_code: int
    html: str | None = None
    location: str | None = None
    retry_after: int | None = None
