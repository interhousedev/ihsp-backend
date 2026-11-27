"""Helpers shared by the activities services: loading, permissions, notifications."""

from datetime import datetime
from uuid import UUID

from app.modules.activities.domain.access import (
    Permission,
    PermissionDeniedError,
    club_permissions,
    global_permissions,
)
from app.modules.activities.domain.club import Club, ClubCapability
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.event import Event
from app.modules.activities.domain.membership import MemberRole, Membership
from app.modules.activities.domain.points import entry_for
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationDraft, NotificationType

ORGANIZER_ROLES = (MemberRole.OWNER, MemberRole.CO_OWNER, MemberRole.TEAM)


async def load_club(p: Ports, club_id: UUID) -> Club:
    """The club with its owner filled in, or 404."""
    club = await p.clubs.get(club_id)
    if club is None:
        raise ActivitiesNotFoundError()
    for m in await p.members.list(club_id):
        if m.role == MemberRole.OWNER and m.is_active:
            club.owner_id = m.user_id
    return club


async def load_event(p: Ports, event_id: UUID) -> Event:
    """One event or 404."""
    event = await p.events.get(event_id)
    if event is None:
        raise ActivitiesNotFoundError()
    return event


async def permissions(p: Ports, actor: Actor, club_id: UUID) -> frozenset[Permission]:
    """Global role permissions plus those of the actor's role in this club."""
    perms = set(global_permissions(actor.roles))
    m = await p.members.get(club_id, actor.user_id)
    if m is not None and m.is_active:
        perms |= club_permissions(m.role)
    return frozenset(perms)


async def require(p: Ports, actor: Actor, club_id: UUID, perm: Permission) -> None:
    """Raise `PermissionDeniedError` unless the actor holds the permission here."""
    if perm not in await permissions(p, actor, club_id):
        raise PermissionDeniedError()


async def require_capability(p: Ports, club_id: UUID, cap: ClubCapability) -> Club:
    """The club when the capability is on, else `CapabilityDisabledError`."""
    club = await load_club(p, club_id)
    club.require(cap)
    return club


async def active_member(p: Ports, club_id: UUID, user_id: UUID) -> Membership | None:
    """The membership when the person is an active member."""
    m = await p.members.get(club_id, user_id)
    return m if m is not None and m.is_active else None


async def organizer_ids(p: Ports, club_id: UUID) -> list[UUID]:
    """Active owners, co-owners and team members."""
    return [
        m.user_id
        for m in await p.members.list(club_id)
        if m.is_active and m.role in ORGANIZER_ROLES
    ]


def note(
    user_id: UUID,
    kind: NotificationType,
    payload: dict[str, object],
    key: str,
    *,
    scheduled_at: datetime | None = None,
) -> NotificationDraft:
    """One notification draft; the recipient's settings pick the channel."""
    return NotificationDraft(
        user_id=user_id,
        type=kind,
        payload=payload,
        dedupe_key=key,
        scheduled_at=scheduled_at,
    )


async def award(
    p: Ports, club: Club, kind: str, user_id: UUID, source_id: UUID
) -> bool:
    """Credit points on the club ledger when the club keeps points; once per source."""
    if ClubCapability.POINTS not in club.capabilities:
        return False
    entry = entry_for(
        kind, user_id, source_id, p.clock.now(), club.points_rules
    ).for_club(club.id)
    return await p.points.add(entry)
