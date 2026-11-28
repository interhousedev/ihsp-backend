"""Club points leaderboard and roster statistics."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    load_club,
    require,
    require_capability,
)
from app.modules.activities.domain.access import Permission
from app.modules.activities.domain.club import ClubCapability, ClubInvalidError
from app.modules.activities.domain.draft import NotClubMemberError
from app.modules.activities.domain.points import (
    DEFAULT_POINTS,
    LeaderRow,
    PointEntry,
    top,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor

from uuid_utils.compat import uuid7

Term = tuple[datetime | None, datetime | None]


class LeaderboardService:
    """Points live on the club that runs the event."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def top(
        self,
        actor: Actor,
        club_id: UUID,
        term: Term | None = None,
        limit: int = 20,
    ) -> list[LeaderRow]:
        """Ranked rows; opted-out students are masked."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.POINTS)
        since, until = term or (None, None)
        totals = await p.points.totals(club_id, since, until)
        names = {u: await p.users.display_name(u) for u in totals}
        return top(totals, names, await p.points.opted_out(), limit)

    async def top_combined(self, actor: Actor, limit: int = 20) -> list[LeaderRow]:
        """One table over the actor's clubs that keep points, summed per student."""
        p = self._p
        totals: dict[UUID, int] = {}
        for m in await p.members.list_for_user(actor.user_id):
            if not m.is_active:
                continue
            club = await load_club(p, m.club_id)
            if ClubCapability.POINTS not in club.capabilities:
                continue
            club_totals = await p.points.totals(club.id, None, None)
            for user_id, points in club_totals.items():
                totals[user_id] = totals.get(user_id, 0) + points
        names = {u: await p.users.display_name(u) for u in totals}
        return top(totals, names, await p.points.opted_out(), limit)

    async def my_points(self, actor: Actor, club_id: UUID) -> dict[str, Any]:
        """The actor's total and entries on this club."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.POINTS)
        entries = await p.points.entries(club_id, actor.user_id)
        return {
            "total": sum(e.points for e in entries),
            "entries": [
                {"reason": e.reason, "points": e.points, "at": e.at} for e in entries
            ],
        }

    async def set_opt_out(self, actor: Actor, opted_out: bool) -> None:
        """Hide or show the actor's name on every leaderboard."""
        await self._p.points.set_opt_out(actor.user_id, opted_out)

    async def attendance(self, actor: Actor, club_id: UUID) -> list[dict[str, Any]]:
        """Per-member attendance and shift counts; organizers only."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.ROSTER)
        await require(p, actor, club_id, Permission.VIEW_MEMBERS)
        rows = []
        for m in await p.members.list(club_id):
            if not m.is_active:
                continue
            counts: dict[str, int] = {}
            for e in await p.points.entries(club_id, m.user_id):
                counts[e.reason] = counts.get(e.reason, 0) + 1
            rows.append(
                {
                    "user_id": m.user_id,
                    "display_name": await p.users.display_name(m.user_id),
                    "attended": counts.get("attended", 0),
                    "shifts": counts.get("draft_completed", 0),
                    "no_shows": counts.get("no_show", 0),
                }
            )
        return rows

    async def get_rules(self, actor: Actor, club_id: UUID) -> dict[str, int]:
        """Points per kind of activity, club overrides over the defaults."""
        club = await require_capability(self._p, club_id, ClubCapability.POINTS)
        return {**DEFAULT_POINTS, **club.points_rules}

    async def set_rules(
        self, actor: Actor, club_id: UUID, rules: dict[str, int]
    ) -> dict[str, int]:
        """Replace the club's point values; club editors only."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.POINTS)
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        for kind, value in rules.items():
            if kind not in DEFAULT_POINTS or not -100 <= value <= 100:
                raise ClubInvalidError(params={"field": kind})
        club = await load_club(p, club_id)
        club.points_rules = dict(rules)
        await p.clubs.save(club)
        return {**DEFAULT_POINTS, **club.points_rules}

    async def award_manual(
        self, actor: Actor, club_id: UUID, user_id: UUID, points: int, reason: str
    ) -> PointEntry:
        """Organizers credit or deduct points by hand."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.POINTS)
        await require(p, actor, club_id, Permission.EDIT_EVENTS)
        if await active_member(p, club_id, user_id) is None:
            raise NotClubMemberError()
        if points == 0 or not -100 <= points <= 100 or not reason.strip():
            raise ClubInvalidError(params={"field": "points"})
        entry = PointEntry(
            user_id,
            "manual",
            uuid7(),
            reason.strip()[:60],
            points,
            p.clock.now(),
            club_id,
        )
        await p.points.add(entry)
        await p.audit.record(actor.user_id, "activities.points.manual", club_id)
        return entry
