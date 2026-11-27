"""Club announcements; recipients' settings choose the delivery channel."""

from __future__ import annotations

import builtins
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.activities.application.common import (
    ORGANIZER_ROLES,
    load_club,
    note,
    require,
)
from app.modules.activities.domain.access import Permission, is_platform_staff
from app.modules.activities.domain.announcement import (
    Announcement,
    check_daily_limit,
    parse_audience,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationDraft, NotificationType


class AnnouncementService:
    """Compose, schedule, cancel and settle announcements."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def send(
        self,
        actor: Actor,
        club_id: UUID,
        text: str,
        audience: str,
        scheduled_at: datetime | None = None,
    ) -> Announcement:
        """Send now, or keep until `scheduled_at`."""
        p = self._p
        await require(p, actor, club_id, Permission.ANNOUNCE)
        await load_club(p, club_id)
        now = p.clock.now()
        check_daily_limit(
            await p.announcements.count_since(club_id, now - timedelta(hours=24)),
            is_staff=is_platform_staff(actor.roles),
        )
        ann = Announcement.compose(
            club_id=club_id,
            author_id=actor.user_id,
            text=text,
            audience=audience,
            now=now,
        )
        if scheduled_at is not None:
            ann.schedule(scheduled_at, now)
            await p.announcements.add(ann)
            return ann
        recipients = await self._deliver(ann)
        ann.mark_sent(now, recipients)
        await p.announcements.add(ann)
        return ann

    async def _recipients(self, ann: Announcement) -> builtins.list[UUID]:
        p = self._p
        kind, event_id = parse_audience(ann.audience)
        if kind == "event":
            event = await p.events.get(event_id) if event_id else None
            if event is None or event.club_id != ann.club_id:
                raise ActivitiesNotFoundError()
            return [
                r.user_id
                for r in await p.events.list_rsvps(event.id)
                if r.status == "going"
            ]
        members = [m for m in await p.members.list(ann.club_id) if m.is_active]
        if kind == "team":
            members = [m for m in members if m.role in ORGANIZER_ROLES]
        return list(dict.fromkeys(m.user_id for m in members))

    async def _deliver(self, ann: Announcement) -> int:
        users = await self._recipients(ann)
        drafts: list[NotificationDraft] = [
            note(
                u,
                NotificationType.CLUB_ANNOUNCEMENT,
                {
                    "club_id": str(ann.club_id),
                    "announcement_id": str(ann.id),
                    "text": ann.text,
                },
                f"activities:announcement:{ann.id}:{u}",
            )
            for u in users
        ]
        await self._p.notifier.send(drafts)
        return len(users)

    async def cancel(self, actor: Actor, announcement_id: UUID) -> Announcement:
        """Withdraw an announcement that was not sent yet."""
        p = self._p
        ann = await p.announcements.get(announcement_id)
        if ann is None:
            raise ActivitiesNotFoundError()
        await require(p, actor, ann.club_id, Permission.ANNOUNCE)
        ann.cancel()
        await p.announcements.save(ann)
        return ann

    async def list(self, actor: Actor, club_id: UUID) -> builtins.list[Announcement]:
        """Announcements of a club for those who may send them."""
        await require(self._p, actor, club_id, Permission.ANNOUNCE)
        return await self._p.announcements.list(club_id)

    async def settle_due(self) -> int:
        """Send scheduled announcements whose time has come."""
        p = self._p
        now = p.clock.now()
        done = 0
        for ann in await p.announcements.list_scheduled():
            if ann.scheduled_at is None or ann.scheduled_at > now:
                continue
            ann.mark_sent(now, await self._deliver(ann))
            await p.announcements.save(ann)
            done += 1
        return done
