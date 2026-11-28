"""Joining, approving, leaving and banning members."""

from __future__ import annotations

import builtins
from dataclasses import dataclass
from uuid import UUID

from app.modules.activities.application.common import (
    load_club,
    note,
    permissions,
    require,
)
from app.modules.activities.domain.access import Permission, PermissionDeniedError
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.membership import (
    JoinNotAllowedError,
    MemberRole,
    Membership,
    MembershipStateError,
    MemberStatus,
    join,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationType


@dataclass(frozen=True, slots=True)
class MemberView:
    """A member as shown to the club team."""

    user_id: UUID
    display_name: str
    role: str
    status: str


class MembershipService:
    """Membership use cases."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def join(
        self, actor: Actor, club_id: UUID, message: str | None = None
    ) -> Membership:
        """Join an active club; the owner is told."""
        p = self._p
        club = await load_club(p, club_id)
        old = await p.members.get(club_id, actor.user_id)
        if old is not None and not old.can_rejoin():
            raise JoinNotAllowedError()
        if old is not None and old.status in (
            MemberStatus.ACTIVE,
            MemberStatus.REQUESTED,
        ):
            return old
        decl = await p.clubs.latest_declaration(club_id)
        m = join(
            club,
            actor.user_id,
            declaration_version=decl.version if decl else 0,
            now=p.clock.now(),
            is_student=await p.users.is_student(actor.user_id),
        )
        await p.members.save(m)
        owners = [
            x.user_id
            for x in await p.members.list(club_id)
            if x.is_active and x.role in (MemberRole.OWNER, MemberRole.CO_OWNER)
        ]
        at = p.clock.now().isoformat()
        await p.notifier.send(
            [
                note(
                    o,
                    NotificationType.CLUB_JOIN_REQUEST,
                    {
                        "club_id": str(club_id),
                        "user_id": str(actor.user_id),
                        "message": message,
                    },
                    f"activities:join:{club_id}:{actor.user_id}:{at}:{o}",
                )
                for o in owners
            ]
        )
        return m

    async def approve(self, actor: Actor, club_id: UUID, user_id: UUID) -> Membership:
        """Admit a requester; the person always gets the result notice."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        m = await p.members.get(club_id, user_id)
        if m is None:
            raise ActivitiesNotFoundError()
        if not m.is_active:
            m.approve(p.clock.now())
            await p.members.save(m)
        stamp = p.clock.now().isoformat()
        await p.notifier.send(
            [
                note(
                    user_id,
                    NotificationType.CLUB_JOIN_RESULT,
                    {"club_id": str(club_id), "approved": True},
                    f"activities:join-result:{club_id}:{user_id}:{stamp}",
                )
            ]
        )
        return m

    async def leave(self, actor: Actor, club_id: UUID) -> None:
        """Leave a club; the owner must transfer first."""
        m = await self._p.members.get(club_id, actor.user_id)
        if m is None:
            raise ActivitiesNotFoundError()
        m.leave(self._p.clock.now())
        await self._p.members.save(m)

    async def decline(self, actor: Actor, club_id: UUID, user_id: UUID) -> Membership:
        """Turn a join request down; the person may ask again."""
        return await self._remove(
            actor, club_id, user_id, MemberStatus.REQUESTED, "activities.member.decline"
        )

    async def remove(self, actor: Actor, club_id: UUID, user_id: UUID) -> Membership:
        """Remove a member without a ban; the person may join again."""
        return await self._remove(
            actor, club_id, user_id, MemberStatus.ACTIVE, "activities.member.remove"
        )

    async def _remove(
        self,
        actor: Actor,
        club_id: UUID,
        user_id: UUID,
        expected: MemberStatus,
        action: str,
    ) -> Membership:
        """Mark a row of the expected status as removed; never the owner."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        m = await p.members.get(club_id, user_id)
        if m is None:
            raise ActivitiesNotFoundError()
        if m.status != expected or m.role == MemberRole.OWNER:
            raise MembershipStateError()
        m.remove()
        m.left_at = p.clock.now()
        await p.members.save(m)
        await p.audit.record(actor.user_id, action, club_id)
        return m

    async def ban(
        self, actor: Actor, club_id: UUID, user_id: UUID, reason: str
    ) -> Membership:
        """Ban a member of this club."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        m = await p.members.get(club_id, user_id)
        if m is None:
            raise ActivitiesNotFoundError()
        if m.role == MemberRole.OWNER:
            raise MembershipStateError()
        m.ban()
        await p.members.save(m)
        await p.audit.record(actor.user_id, "activities.member.ban", club_id)
        return m

    async def list(self, actor: Actor, club_id: UUID) -> builtins.list[Membership]:
        """Every membership row of a club, for the team."""
        await require(self._p, actor, club_id, Permission.VIEW_MEMBERS)
        return await self._p.members.list(club_id)

    async def members(self, actor: Actor, club_id: UUID) -> builtins.list[MemberView]:
        """Active members with names; club editors also see the join requests."""
        granted = await permissions(self._p, actor, club_id)
        if Permission.VIEW_MEMBERS not in granted:
            raise PermissionDeniedError()
        shown = {MemberStatus.ACTIVE}
        if Permission.EDIT_CLUB in granted:
            shown.add(MemberStatus.REQUESTED)
        rows = [m for m in await self._p.members.list(club_id) if m.status in shown]
        return [
            MemberView(
                m.user_id,
                await self._p.users.display_name(m.user_id),
                str(m.role),
                str(m.status),
            )
            for m in rows
        ]
