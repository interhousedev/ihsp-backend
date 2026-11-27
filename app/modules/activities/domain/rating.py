"""Anonymous-to-club ratings of events and clubs."""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.domain.access import PermissionDeniedError
from app.modules.activities.domain.errors import Conflict, Invalid
from app.modules.activities.domain.event import Event
from app.shared.actor import Role

__all__ = [
    "ASPECTS",
    "EVENT_RATING_WINDOW",
    "MAX_COMMENT",
    "CLUB_MIN_MEMBERSHIP",
    "Rating",
    "RatingInvalidError",
    "RatingNotAllowedError",
    "RevealAudit",
    "aggregates",
    "owner_view",
    "rate_club",
    "rate_event",
    "reveal_author",
]

MAX_COMMENT = 1000
ASPECTS = ("organization", "usefulness", "atmosphere")
EVENT_RATING_WINDOW = timedelta(days=14)
CLUB_MIN_MEMBERSHIP = timedelta(days=30)


class RatingInvalidError(Invalid):
    """The rating input is invalid."""


class RatingNotAllowedError(Conflict):
    """The person may not rate this now."""


@dataclass(slots=True)
class Rating:
    """A 1..5 rating with optional aspects and comment."""

    target_type: str
    target_id: UUID
    user_id: UUID
    score: int
    aspects: dict[str, int]
    comment: str | None
    anonymous_to_club: bool
    created_at: datetime
    id: UUID = field(default_factory=uuid4)


def _build(
    target_type: str,
    target_id: UUID,
    user_id: UUID,
    now: datetime,
    score: int,
    aspects: dict[str, int],
    comment: str | None,
    anonymous: bool,
) -> Rating:
    if not 1 <= score <= 5:
        raise RatingInvalidError(params={"field": "score"})
    for key, value in aspects.items():
        if key not in ASPECTS or not 1 <= value <= 5:
            raise RatingInvalidError(params={"field": key})
    if comment is not None and len(comment) > MAX_COMMENT:
        raise RatingInvalidError(params={"field": "comment"})
    return Rating(
        target_type, target_id, user_id, score, dict(aspects), comment, anonymous, now
    )


def rate_event(
    event: Event,
    *,
    checked_in: bool,
    now: datetime,
    user_id: UUID,
    score: int,
    aspects: dict[str, int],
    comment: str | None = None,
    anonymous_to_club: bool = False,
) -> Rating:
    """Only checked-in attendees, from the end until 14 days later."""
    rating = _build(
        "event", event.id, user_id, now, score, aspects, comment, anonymous_to_club
    )
    if (
        not checked_in
        or not event.ends_at <= now <= event.ends_at + EVENT_RATING_WINDOW
    ):
        raise RatingNotAllowedError()
    return rating


def rate_club(
    club_id: UUID,
    user_id: UUID,
    *,
    joined_at: datetime,
    now: datetime,
    already_rated_this_term: bool,
    score: int,
    aspects: dict[str, int],
    comment: str | None = None,
    anonymous_to_club: bool = False,
) -> Rating:
    """Members of at least 30 days, once per term."""
    rating = _build(
        "club", club_id, user_id, now, score, aspects, comment, anonymous_to_club
    )
    if already_rated_this_term or now - joined_at < CLUB_MIN_MEMBERSHIP:
        raise RatingNotAllowedError()
    return rating


def aggregates(ratings: list[Rating]) -> dict[str, Any]:
    """Count, average score and average per aspect."""
    if not ratings:
        return {"count": 0, "avg": None, "aspects": {}}
    per: dict[str, list[int]] = {}
    for r in ratings:
        for key, value in r.aspects.items():
            per.setdefault(key, []).append(value)
    return {
        "count": len(ratings),
        "avg": sum(r.score for r in ratings) / len(ratings),
        "aspects": {k: sum(v) / len(v) for k, v in per.items()},
    }


def owner_view(rating: Rating) -> dict[str, Any]:
    """What a club owner sees; the author only when not anonymous."""
    view: dict[str, Any] = {
        "id": rating.id,
        "score": rating.score,
        "aspects": dict(rating.aspects),
        "comment": rating.comment,
        "created_at": rating.created_at,
    }
    if not rating.anonymous_to_club:
        view["user_id"] = rating.user_id
    return view


@dataclass(frozen=True, slots=True)
class RevealAudit:
    """The fact that an administrator unmasked an author."""

    rating_id: UUID
    revealed_user_id: UUID
    by_user: UUID
    reason: str


def reveal_author(
    rating: Rating, *, by_user: UUID, roles: frozenset[Role], reason: str
) -> RevealAudit:
    """Administrators only (never SU or club owners); the reason is mandatory."""
    if not roles & {Role.ADMIN, Role.ACTIVITIES_ADMIN}:
        raise PermissionDeniedError()
    if not reason.strip():
        raise ValueError("a reason is required")
    return RevealAudit(rating.id, rating.user_id, by_user, reason.strip())
