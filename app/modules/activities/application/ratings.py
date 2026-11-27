"""Ratings of events and clubs; authors stay hidden from the club."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    load_club,
    load_event,
    require,
)
from app.modules.activities.domain.access import Permission, PermissionDeniedError
from app.modules.activities.domain.club import ClubStatus
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.rating import (
    Rating,
    aggregates,
    owner_view,
)
from app.modules.activities.domain.rating import rate_club as build_club_rating
from app.modules.activities.domain.rating import rate_event as build_event_rating
from app.modules.activities.domain.rating import reveal_author as build_reveal
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor

_TERM = timedelta(days=120)


class RatingService:
    """Rate, summarise and (for administrators) unmask."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def rate_event(
        self,
        actor: Actor,
        event_id: UUID,
        score: int,
        aspects: dict[str, int],
        comment: str | None = None,
        anonymous_to_club: bool = False,
    ) -> Rating:
        """A checked-in attendee rates an event."""
        p = self._p
        event = await load_event(p, event_id)
        rsvp = await p.events.get_rsvp(event_id, actor.user_id)
        rating = build_event_rating(
            event,
            checked_in=rsvp is not None and rsvp.checked_in_at is not None,
            now=p.clock.now(),
            user_id=actor.user_id,
            score=score,
            aspects=aspects,
            comment=comment,
            anonymous_to_club=anonymous_to_club,
        )
        await p.ratings.add(rating)
        return rating

    async def rate_club(
        self,
        actor: Actor,
        club_id: UUID,
        score: int,
        aspects: dict[str, int],
        comment: str | None = None,
        anonymous_to_club: bool = False,
    ) -> Rating:
        """A long-standing member rates the club once per term."""
        p = self._p
        member = await active_member(p, club_id, actor.user_id)
        if member is None or member.joined_at is None:
            raise ActivitiesNotFoundError()
        now = p.clock.now()
        done = any(
            r.user_id == actor.user_id and now - r.created_at < _TERM
            for r in await p.ratings.list_for("club", club_id)
        )
        rating = build_club_rating(
            club_id,
            actor.user_id,
            joined_at=member.joined_at,
            now=now,
            already_rated_this_term=done,
            score=score,
            aspects=aspects,
            comment=comment,
            anonymous_to_club=anonymous_to_club,
        )
        await p.ratings.add(rating)
        return rating

    async def summary(self, actor: Actor, club_id: UUID) -> dict[str, Any]:
        """Aggregates for members and viewers; comments only for organizers."""
        p = self._p
        club = await load_club(p, club_id)
        staff = True
        try:
            await require(p, actor, club_id, Permission.EDIT_EVENTS)
        except (PermissionDeniedError, ActivitiesNotFoundError):
            staff = False
            member = await active_member(p, club_id, actor.user_id)
            if member is None and club.status != ClubStatus.ACTIVE:
                raise ActivitiesNotFoundError() from None
        event_ratings: list[Rating] = []
        for event in await p.events.list_for_club(club_id):
            event_ratings += await p.ratings.list_for("event", event.id)
        club_ratings = await p.ratings.list_for("club", club_id)
        commented = [r for r in event_ratings + club_ratings if r.comment]
        return {
            "events": aggregates(event_ratings),
            "club": aggregates(club_ratings),
            "comments": [owner_view(r) for r in commented] if staff else [],
        }

    async def reveal_author(self, actor: Actor, rating_id: UUID, reason: str) -> Rating:
        """Administrators unmask an author; audited, reason required."""
        p = self._p
        rating = await p.ratings.get(rating_id)
        if rating is None:
            raise ActivitiesNotFoundError()
        build_reveal(rating, by_user=actor.user_id, roles=actor.roles, reason=reason)
        await p.audit.record(
            actor.user_id, "activities.rating.reveal_author", rating.id
        )
        return rating
