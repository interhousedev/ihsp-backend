"""Club member profiles (reusable form answers)."""

from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    load_club,
    permissions,
    require,
    require_capability,
)
from app.modules.activities.domain.access import Permission, PermissionDeniedError
from app.modules.activities.domain.club import ClubCapability, ClubInvalidError
from app.modules.activities.domain.draft import ClubProfile, NotClubMemberError
from app.modules.activities.domain.membership import MemberRole
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor

FIELD_TYPES = frozenset({"text", "textarea", "select", "checkbox", "number", "date"})
_ANSWER_READERS = frozenset({MemberRole.OWNER, MemberRole.CO_OWNER})
MAX_FIELDS = 30


def validate_fields(raw: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Clean form field definitions: unique keys, known types, options for selects."""
    if len(raw) > MAX_FIELDS:
        raise ClubInvalidError(params={"field": "form_fields"})
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for f in raw:
        key = str(f.get("key", "")).strip()
        kind = f.get("type", "text")
        options = f.get("options") or []
        if (
            not key
            or len(key) > 60
            or key in seen
            or kind not in FIELD_TYPES
            or not f.get("label")
            or not isinstance(options, list)
            or (kind == "select" and not options)
        ):
            raise ClubInvalidError(params={"field": key or "key"})
        seen.add(key)
        out.append(
            {
                "key": key,
                "label": f["label"],
                "type": kind,
                "required": bool(f.get("required", False)),
                "options": options if kind == "select" else [],
            }
        )
    return out


class FormsService:
    """Forms serve active members only."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def save_profile(
        self, actor: Actor, club_id: UUID, answers: dict[str, Any]
    ) -> ClubProfile:
        """Store the member's answers for this club."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.FORMS)
        if await active_member(p, club_id, actor.user_id) is None:
            raise NotClubMemberError()
        now = p.clock.now()
        profile = await p.drafts.get_profile(actor.user_id, club_id)
        if profile is None:
            profile = ClubProfile(actor.user_id, club_id, dict(answers), now)
        else:
            profile.upsert(answers, now)
        await p.drafts.save_profile(profile)
        return profile

    async def my_profile(self, actor: Actor, club_id: UUID) -> ClubProfile | None:
        """The member's stored answers."""
        await require_capability(self._p, club_id, ClubCapability.FORMS)
        return await self._p.drafts.get_profile(actor.user_id, club_id)

    async def get_fields(self, actor: Actor, club_id: UUID) -> list[dict[str, Any]]:
        """The club's form questions; members and organizers read them."""
        p = self._p
        club = await require_capability(p, club_id, ClubCapability.FORMS)
        if await active_member(p, club_id, actor.user_id) is None and not (
            await permissions(p, actor, club_id)
        ):
            raise PermissionDeniedError()
        return list(club.form_fields)

    async def set_fields(
        self, actor: Actor, club_id: UUID, fields: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        """Replace the form questions; club editors only."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.FORMS)
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        club = await load_club(p, club_id)
        club.form_fields = validate_fields(fields)
        await p.clubs.save(club)
        return club.form_fields

    async def answers(
        self, actor: Actor, club_id: UUID
    ) -> list[tuple[ClubProfile, str]]:
        """Every member's stored answers; the founder and co-owners only."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.FORMS)
        me = await p.members.get(club_id, actor.user_id)
        if me is None or not me.is_active or me.role not in _ANSWER_READERS:
            raise PermissionDeniedError()
        active = {m.user_id for m in await p.members.list(club_id) if m.is_active}
        return [
            (x, await p.users.display_name(x.user_id))
            for x in await p.drafts.list_profiles(club_id)
            if x.user_id in active
        ]
