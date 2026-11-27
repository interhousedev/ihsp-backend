"""Platform-wide activities numbers for staff."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.activities.domain.access import (
    PermissionDeniedError,
    is_platform_staff,
)
from app.modules.activities.domain.event import EventStatus
from app.modules.activities.domain.membership import MemberStatus
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor


class AnalyticsService:
    """Read-only overview."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def overview(
        self, actor: Actor, since: datetime | None, until: datetime | None
    ) -> dict[str, Any]:
        """Clubs by status, events, RSVPs and check-ins in the period."""
        p = self._p
        if not is_platform_staff(actor.roles):
            raise PermissionDeniedError()
        clubs: dict[str, int] = {}
        for c in await p.clubs.list_all():
            clubs[str(c.status)] = clubs.get(str(c.status), 0) + 1
        events = [
            e
            for e in await p.events.list_all()
            if e.status not in (EventStatus.DRAFT, EventStatus.CANCELLED)
            and (since is None or e.starts_at >= since)
            and (until is None or e.starts_at < until)
        ]
        rsvps = check_ins = 0
        per: dict[UUID, dict[str, int]] = {}
        for e in events:
            cs = per.setdefault(e.club_id, {"events": 0, "rsvps": 0, "check_ins": 0})
            cs["events"] += 1
            for r in await p.events.list_rsvps(e.id):
                if r.status != "cancelled":
                    rsvps += 1
                    cs["rsvps"] += 1
                if r.checked_in_at is not None:
                    check_ins += 1
                    cs["check_ins"] += 1
        per_club = []
        for c in await p.clubs.list_all():
            cs = per.get(c.id, {"events": 0, "rsvps": 0, "check_ins": 0})
            members = sum(
                1 for m in await p.members.list(c.id) if m.status == MemberStatus.ACTIVE
            )
            scores = [r.score for r in await p.ratings.list_for("club", c.id)]
            per_club.append(
                {
                    "club_id": c.id,
                    "slug": c.slug,
                    "name": c.name,
                    "status": str(c.status),
                    "members": members,
                    "events": cs["events"],
                    "attendance_rate": (
                        round(cs["check_ins"] / cs["rsvps"], 4) if cs["rsvps"] else None
                    ),
                    "avg_rating": (
                        round(sum(scores) / len(scores), 2) if scores else None
                    ),
                }
            )
        return {
            "clubs": {"active": clubs.get("active", 0), "by_status": clubs},
            "events": len(events),
            "rsvps": rsvps,
            "check_ins": check_ins,
            "per_club": per_club,
        }
