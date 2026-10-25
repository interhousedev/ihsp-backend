"""Platform feedback ("call for improvements"): ideas, bug reports and the rest."""

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import TypeVar
from uuid import UUID

from app.modules.feedback.domain.errors import FeedbackInvalidError

MAX_TITLE = 120
MAX_DESCRIPTION = 4000
MAX_RESPONSE = 4000
MAX_PAGE_URL = 500
MAX_ATTACHMENTS = 10
DAILY_LIMIT = 10
"""Feedback one user may send per day (across web and bot)."""

E = TypeVar("E", bound=StrEnum)


class FeedbackKind(StrEnum):
    """What the feedback is."""

    IDEA = "idea"
    BUG = "bug"
    OTHER = "other"


class FeedbackArea(StrEnum):
    """Which part of the platform it is about."""

    ID = "id"
    MY = "my"
    STAFF = "staff"
    ADMIN = "admin"
    LMS = "lms"
    LIBRARY = "library"
    SHARE = "share"
    BOT = "bot"
    AI = "ai"
    NOTEBOOKS = "notebooks"
    MAIL = "mail"
    OTHER = "other"


class FeedbackStatus(StrEnum):
    """Where the feedback is in its review."""

    NEW = "new"
    IN_REVIEW = "in_review"
    PLANNED = "planned"
    DONE = "done"
    REJECTED = "rejected"


class FeedbackSource(StrEnum):
    """Where the feedback was sent from."""

    WEB = "web"
    BOT = "bot"


class ResponseChannel(StrEnum):
    """How an administrator's response reaches the reporter."""

    TELEGRAM = "telegram"
    MAIL = "mail"


class DeliveryStatus(StrEnum):
    """Outcome of one channel: queued/sent, failed, or not possible for the user."""

    SENT = "sent"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True, slots=True)
class Delivery:
    """The outcome of one channel of a response."""

    channel: ResponseChannel
    status: DeliveryStatus


@dataclass(slots=True)
class Feedback:
    """One feedback item; ``response_count`` is filled by the repository."""

    id: UUID
    reporter_id: UUID
    kind: FeedbackKind
    area: FeedbackArea
    title: str
    description: str
    status: FeedbackStatus
    source: FeedbackSource
    created_at: datetime
    updated_at: datetime
    page_url: str | None = None
    attachment_file_ids: list[UUID] = field(default_factory=list)
    response_count: int = 0


@dataclass(slots=True)
class FeedbackResponse:
    """An administrator's answer to a feedback item."""

    id: UUID
    feedback_id: UUID
    author_id: UUID
    text: str
    channels: list[ResponseChannel]
    deliveries: list[Delivery]
    created_at: datetime
    attachment_file_ids: list[UUID] = field(default_factory=list)


def _text(value: str, name: str, limit: int) -> str:
    clean = value.strip()
    if not clean or len(clean) > limit:
        raise FeedbackInvalidError(params={"field": name, "max_length": limit})
    return clean


def normalize_title(value: str) -> str:
    """Trim the title; 1 to 120 characters."""
    return _text(value, "title", MAX_TITLE)


def normalize_description(value: str) -> str:
    """Trim the description; 1 to 4000 characters."""
    return _text(value, "description", MAX_DESCRIPTION)


def normalize_response(value: str) -> str:
    """Trim a response text; 1 to 4000 characters."""
    return _text(value, "text", MAX_RESPONSE)


def normalize_page_url(value: str | None) -> str | None:
    """Trim the page URL; empty means none; at most 500 characters."""
    clean = (value or "").strip()
    if len(clean) > MAX_PAGE_URL:
        raise FeedbackInvalidError(
            params={"field": "page_url", "max_length": MAX_PAGE_URL}
        )
    return clean or None


def parse_enum(enum: type[E], value: str | E, name: str) -> E:
    """Return the enum member or raise FeedbackInvalidError(field=name)."""
    try:
        return enum(value)
    except ValueError as exc:
        raise FeedbackInvalidError(params={"field": name}) from exc


def unique_ids(ids: list[UUID] | tuple[UUID, ...]) -> list[UUID]:
    """Drop repeated ids, keep the order."""
    return list(dict.fromkeys(ids))
