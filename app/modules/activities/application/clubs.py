"""Clubs: create, review, update, capabilities."""

from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    load_club,
    permissions,
    require,
)
from app.modules.activities.domain.access import (
    Permission,
    PermissionDeniedError,
    is_platform_staff,
)
from app.modules.activities.domain.club import (
    Club,
    ClubCapability,
    ClubInvalidError,
    ClubKind,
    ClubStatus,
    Declaration,
    JoinPolicy,
    next_declaration,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.membership import (
    MemberRole,
    Membership,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor, Role

_EDITABLE = frozenset(
    {
        "name",
        "description",
        "join_policy",
        "visibility_public",
        "contact_enabled",
        "logo_file_id",
    }
)


class ClubService:
    """Club lifecycle."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def create(
        self, actor: Actor, name: str, slug: str, description: str = "", **kw: Any
    ) -> Club:
        """A draft club; the creator becomes its owner."""
        p = self._p
        if not name.strip():
            raise ClubInvalidError(params={"field": "name"})
        if await p.clubs.get_by_slug(slug) is not None:
            raise ClubInvalidError(params={"field": "slug"})
        extra = set(kw) - _EDITABLE
        if extra:
            raise ClubInvalidError(params={"field": sorted(extra)[0]})
        club = Club(uuid7(), slug, ClubKind.CLUB, name.strip(), actor.user_id)
        club.description = description
        _apply(club, kw)
        club.validate()
        await p.clubs.add(club)
        await p.members.save(
            Membership(
                club.id,
                actor.user_id,
                MemberRole.OWNER,
                MemberStatus.ACTIVE,
                0,
                p.clock.now(),
                None,
            )
        )
        return await load_club(p, club.id)

    async def get(self, actor: Actor, club_id: UUID) -> Club:
        """A club; unpublished ones only for members and platform staff."""
        club = await load_club(self._p, club_id)
        if club.status == ClubStatus.ACTIVE and club.visibility_public:
            return club
        if not await permissions(self._p, actor, club_id):
            raise ActivitiesNotFoundError()
        return club

    async def submit(self, actor: Actor, club_id: UUID) -> Club:
        """Send a draft club to review."""
        await require(self._p, actor, club_id, Permission.EDIT_CLUB)
        club = await load_club(self._p, club_id)
        club.submit()
        await self._p.clubs.save(club)
        return club

    async def review(
        self, actor: Actor, club_id: UUID, approve: bool, reason: str | None
    ) -> Club:
        """SU approves or returns a club."""
        if Role.SU not in actor.roles:
            raise PermissionDeniedError()
        club = await load_club(self._p, club_id)
        club.review(approve, reason, by_su=True)
        await self._p.clubs.save(club)
        await self._p.audit.record(actor.user_id, "activities.club.review", club.id)
        return club

    async def suspend(self, actor: Actor, club_id: UUID, reason: str) -> Club:
        """Platform staff hide an active club."""
        if not is_platform_staff(actor.roles):
            raise PermissionDeniedError()
        if not reason.strip():
            raise ClubInvalidError(params={"field": "reason"})
        club = await load_club(self._p, club_id)
        club.suspend()
        await self._p.clubs.save(club)
        await self._p.audit.record(actor.user_id, "activities.club.suspend", club.id)
        return club

    async def update(self, actor: Actor, club_id: UUID, **fields: Any) -> Club:
        """Edit the public settings."""
        await require(self._p, actor, club_id, Permission.EDIT_CLUB)
        extra = set(fields) - _EDITABLE
        if extra:
            raise ClubInvalidError(params={"field": sorted(extra)[0]})
        club = await load_club(self._p, club_id)
        _apply(club, fields)
        await self._p.clubs.save(club)
        return club

    async def declare(
        self,
        actor: Actor,
        club_id: UUID,
        *,
        goals: Any,
        rules: Any,
        meeting_schedule: Any,
        requirements: Any,
    ) -> Declaration:
        """Publish the next declaration version members agree to."""
        await require(self._p, actor, club_id, Permission.EDIT_CLUB)
        decl = next_declaration(
            await self._p.clubs.latest_declaration(club_id),
            club_id=club_id,
            goals=goals,
            rules=rules,
            meeting_schedule=meeting_schedule,
            requirements=requirements,
        )
        await self._p.clubs.add_declaration(decl)
        return decl

    async def list_mine(self, actor: Actor) -> list[Club]:
        """Clubs the actor belongs to."""
        out = []
        for m in await self._p.members.list_for_user(actor.user_id):
            if m.is_active:
                out.append(await load_club(self._p, m.club_id))
        return out

    async def set_capabilities(
        self, actor: Actor, club_id: UUID, caps: set[ClubCapability]
    ) -> Club:
        """SU and administrators switch forms, drafting, points and roster."""
        if not actor.roles & {Role.SU, Role.ADMIN, Role.ACTIVITIES_ADMIN}:
            raise PermissionDeniedError()
        club = await load_club(self._p, club_id)
        club.set_capabilities(set(caps), by_su=True)
        await self._p.clubs.save(club)
        await self._p.audit.record(
            actor.user_id, "activities.club.capabilities", club.id
        )
        return club


def _apply(club: Club, fields: dict[str, Any]) -> None:
    for key, value in fields.items():
        if key == "join_policy":
            value = JoinPolicy(value)
        setattr(club, key, value)
