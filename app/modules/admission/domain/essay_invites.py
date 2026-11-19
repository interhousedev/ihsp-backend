"""Essay review invites: guest links, anchored feedback and its reanchoring."""

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Final, Literal, get_args
from uuid import UUID

from app.modules.admission.domain.calendar import new_token, token_hash
from app.modules.admission.domain.errors import CharLimitError, InviteNotFoundError
from app.shared.base_error import ValidationFailedError

INVITE_TTL_DAYS: Final = 30
"""Default lifetime of a review link."""
MAX_TTL_DAYS: Final = 90
"""Longest lifetime a student may choose."""
MAX_ACTIVE_INVITES: Final = 20
"""Active (not revoked, not expired) links per essay."""
BODY_MAX: Final = 2000
"""Characters in one comment."""
QUOTE_MAX: Final = 500
"""Characters of the quoted span."""
AUTHOR_MAX: Final = 60
"""Characters of the reviewer's name."""
LABEL_MAX: Final = 60
"""Characters of the student's label for a link."""
COMMENTS_PER_HOUR: Final = 20
"""Comments one link may post per hour."""
OPENS_PER_HOUR: Final = 60
"""Link opens one client address may make per hour."""

Audience = Literal["classmate", "parent", "counselor", "other"]
AUDIENCES: Final[tuple[str, ...]] = get_args(Audience)

__all__ = [
    "AUDIENCES",
    "Anchor",
    "Audience",
    "EssayInvite",
    "Feedback",
    "check_text",
    "check_ttl",
    "new_token",
    "reanchor",
    "token_hash",
]


@dataclass(frozen=True, slots=True)
class EssayInvite:
    """A review link of one essay; only the token hash is kept."""

    id: UUID
    essay_id: UUID
    student_id: UUID
    token_hash: str
    label: str | None
    audience: Audience
    can_comment: bool
    expires_at: datetime
    revoked_at: datetime | None = None
    created_at: datetime | None = None
    last_opened_at: datetime | None = None

    def is_active(self, now: datetime) -> bool:
        """Return whether the link still works at `now`."""
        return self.revoked_at is None and self.expires_at > now

    def require_active(self, now: datetime) -> "EssayInvite":
        """Return the invite, or raise the one not-found answer."""
        if not self.is_active(now):
            raise InviteNotFoundError()
        return self

    def opened(self, now: datetime) -> "EssayInvite":
        """Return the invite stamped as opened at `now`."""
        return replace(self, last_opened_at=now)


@dataclass(frozen=True, slots=True)
class Feedback:
    """A comment on an essay: a guest's, the student's own note, or a reply."""

    id: UUID
    essay_id: UUID
    student_id: UUID
    invite_id: UUID | None
    parent_id: UUID | None
    quote: str | None
    anchor_start: int | None
    anchor_end: int | None
    body: str
    author_name: str
    audience: Audience | None
    created_at: datetime
    resolved_at: datetime | None = None


@dataclass(frozen=True, slots=True)
class Anchor:
    """Where a quote sits in the current text; detached when it is gone."""

    start: int | None
    end: int | None
    detached: bool


def check_ttl(days: int) -> timedelta:
    """Return the lifetime of a link.

    Args:
        days: Requested lifetime in days.

    Returns:
        The lifetime.

    Raises:
        ValidationFailedError: When days is outside 1..MAX_TTL_DAYS.
    """
    if not 1 <= days <= MAX_TTL_DAYS:
        raise ValidationFailedError(params={"field": "ttl_days"})
    return timedelta(days=days)


def check_text(field: str, value: str | None, limit: int) -> str | None:
    """Return the stripped text, None when empty; raise when it is too long.

    Args:
        field: Field name for the error.
        value: The text.
        limit: Largest number of characters.

    Returns:
        The stripped text or None.

    Raises:
        CharLimitError: When the text is longer than the limit.
    """
    if value is None:
        return None
    text = value.strip()
    if len(text) > limit:
        raise CharLimitError(params={"field": field, "limit": limit})
    return text or None


def _nearest(text: str, quote: str, start: int) -> int | None:
    """Return the occurrence of the quote nearest to `start`."""
    best: int | None = None
    at = text.find(quote)
    while at != -1:
        if best is None or abs(at - start) < abs(best - start):
            best = at
        at = text.find(quote, at + 1)
    return best


def reanchor(
    text: str, quote: str | None, start: int | None, end: int | None
) -> Anchor:
    """Place a stored quote in the current essay text.

    Args:
        text: The current essay body.
        quote: The quoted span, None for a general comment.
        start: Stored start offset.
        end: Stored end offset.

    Returns:
        The old offsets when the quote is still there, the nearest occurrence
        when it moved, or a detached anchor when it is gone.
    """
    if not quote:
        return Anchor(start, end, False)
    if start is not None and text[start : start + len(quote)] == quote:
        return Anchor(start, start + len(quote), False)
    found = _nearest(text, quote, start or 0)
    if found is None:
        return Anchor(None, None, True)
    return Anchor(found, found + len(quote), False)
