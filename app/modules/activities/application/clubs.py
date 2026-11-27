"""Clubs: create, review, update, capabilities."""

from dataclasses import dataclass
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
    MemberStatus,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor, Role

from uuid_utils.compat import uuid7


@dataclass(frozen=True, slots=True)
class AdminClubRow:
    """A club with figures for the admin list."""

    club: Club
    owner_name: str | None
    member_count: int


_EDITABLE = frozenset(
    {
        "name",
        "description",
        "join_policy",
        "visibility_public",
        "contact_enabled",
        "logo_file_id",
        "category",
        "goals",
        "rules",
        "schedule",
        "partners",
    }
)


@dataclass(frozen=True, slots=True)
class DirectoryRow:
    """A club in the directory with its size and the caller's place in it."""

    club: Club
    member_count: int
    my_role: str | None
    my_status: str | None


@dataclass(frozen=True, slots=True)
class MyClubState:
    """What the caller is and may do in one club."""

    club_id: UUID
    role: str | None
    status: str | None
    is_member: bool
    is_organizer: bool
    can_edit: bool
    can_manage_events: bool
    can_view_members: bool
    can_approve: bool


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
        club.validate_profile()
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

    async def resume(self, actor: Actor, club_id: UUID) -> Club:
        """Platform staff bring a suspended club back."""
        if not is_platform_staff(actor.roles):
            raise PermissionDeniedError()
        club = await load_club(self._p, club_id)
        club.resume()
        await self._p.clubs.save(club)
        await self._p.audit.record(actor.user_id, "activities.club.resume", club.id)
        return club

    async def list_admin(
        self, actor: Actor, status: ClubStatus | None, limit: int, offset: int
    ) -> tuple[list[AdminClubRow], int]:
        """Every club of any status with owner name and member count."""
        if not is_platform_staff(actor.roles):
            raise PermissionDeniedError()
        p = self._p
        clubs = [
            c for c in await p.clubs.list_all() if status is None or c.status == status
        ]
        clubs.sort(key=lambda c: c.slug)
        rows: list[AdminClubRow] = []
        for c in clubs[offset : offset + limit]:
            members = await p.members.list(c.id)
            count = sum(1 for m in members if m.status == MemberStatus.ACTIVE)
            owner = c.owner_id
            rows.append(
                AdminClubRow(
                    club=c,
                    owner_name=(await p.users.display_name(owner) if owner else None),
                    member_count=count,
                )
            )
        return rows, len(clubs)

    async def update(self, actor: Actor, club_id: UUID, **fields: Any) -> Club:
        """Edit the public settings."""
        await require(self._p, actor, club_id, Permission.EDIT_CLUB)
        extra = set(fields) - _EDITABLE
        if extra:
            raise ClubInvalidError(params={"field": sorted(extra)[0]})
        club = await load_club(self._p, club_id)
        _apply(club, fields)
        club.validate_profile()
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

    async def directory(self, actor: Actor) -> list[DirectoryRow]:
        """Active public clubs plus every club the caller belongs to."""
        p = self._p
        mine = {m.club_id: m for m in await p.members.list_for_user(actor.user_id)}
        rows: list[DirectoryRow] = []
        for c in sorted(await p.clubs.list_all(), key=lambda c: c.slug):
            m = mine.get(c.id)
            public = c.status == ClubStatus.ACTIVE and c.visibility_public
            if not public and m is None:
                continue
            members = await p.members.list(c.id)
            rows.append(
                DirectoryRow(
                    club=await load_club(p, c.id),
                    member_count=sum(1 for x in members if x.is_active),
                    my_role=str(m.role) if m else None,
                    my_status=str(m.status) if m else None,
                )
            )
        return rows

    async def my_state(self, actor: Actor, club_id: UUID) -> MyClubState:
        """The caller's membership, role and staff flags in a club."""
        p = self._p
        club = await self.get(actor, club_id)
        m = await p.members.get(club.id, actor.user_id)
        perms = await permissions(p, actor, club.id)
        active = m is not None and m.is_active
        return MyClubState(
            club_id=club.id,
            role=str(m.role) if m else None,
            status=str(m.status) if m else None,
            is_member=active,
            is_organizer=m is not None and active and m.role != MemberRole.MEMBER,
            can_edit=Permission.EDIT_CLUB in perms,
            can_manage_events=Permission.EDIT_EVENTS in perms,
            can_view_members=Permission.VIEW_MEMBERS in perms,
            can_approve=Permission.APPROVE in perms,
        )

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
