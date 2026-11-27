"""Volunteer drafting: rounds, signups, ranking, picks, invitations, no-shows."""

from datetime import timedelta
from typing import Any
from uuid import UUID

from app.modules.activities.application.common import (
    active_member,
    award,
    load_club,
    load_event,
    note,
    require,
    require_capability,
)
from app.modules.activities.domain.access import Permission, PermissionDeniedError
from app.modules.activities.domain.club import ClubCapability
from app.modules.activities.domain.draft import (
    DraftInvalidError,
    DraftPick,
    DraftRound,
    DraftSignup,
)
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.event import EventStatus
from app.modules.activities.domain.ranking import (
    Candidate,
    Ranked,
    Requirements,
    rank_candidates,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationType

NO_SHOW_GRACE = timedelta(hours=2)
_TAKEN = ("proposed", "invited", "accepted", "completed")


def _strings(value: Any) -> frozenset[str]:
    return frozenset(str(v) for v in value) if isinstance(value, list) else frozenset()


class DraftService:
    """Calls for volunteers, scoped to one club and its drafting capability."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def _round(self, round_id: UUID) -> DraftRound:
        rnd = await self._p.drafts.get_round(round_id)
        if rnd is None:
            raise ActivitiesNotFoundError()
        return rnd

    async def _pick(self, pick_id: UUID) -> tuple[DraftPick, DraftRound]:
        pick = await self._p.drafts.get_pick(pick_id)
        if pick is None:
            raise ActivitiesNotFoundError()
        return pick, await self._round(pick.round_id)

    async def open_round(
        self, actor: Actor, event_id: UUID, club_id: UUID, needed: dict[str, int]
    ) -> DraftRound:
        """Open a call for the club's own event; organizers of that club only."""
        p = self._p
        event = await load_event(p, event_id)
        await require(p, actor, club_id, Permission.EDIT_EVENTS)
        club = await load_club(p, club_id)
        rnd = DraftRound.open(
            event_id, club_id, needed, club=club, event_club_id=event.club_id
        )
        await p.drafts.add_round(rnd)
        return rnd

    async def signup(
        self, actor: Actor, round_id: UUID, role: str, answers: dict[str, Any]
    ) -> DraftSignup:
        """A club member offers to fill a role."""
        p = self._p
        rnd = await self._round(round_id)
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        member = await active_member(p, rnd.club_id, actor.user_id) is not None
        signup = DraftSignup.submit(
            rnd,
            actor.user_id,
            role,
            answers,
            member,
            await p.drafts.list_signups(round_id),
        )
        await p.drafts.add_signup(signup)
        return signup

    async def list_rounds(self, actor: Actor, club_id: UUID) -> list[DraftRound]:
        """Calls of the club; members and organizers only."""
        p = self._p
        await require_capability(p, club_id, ClubCapability.DRAFTING)
        if await active_member(p, club_id, actor.user_id) is None:
            await require(p, actor, club_id, Permission.EDIT_EVENTS)
        return await p.drafts.list_rounds(club_id)

    async def list_signups(self, actor: Actor, round_id: UUID) -> list[DraftSignup]:
        """Who offered to help; organizers only."""
        p = self._p
        rnd = await self._round(round_id)
        await require(p, actor, rnd.club_id, Permission.EDIT_EVENTS)
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        return await p.drafts.list_signups(round_id)

    async def rank(self, actor: Actor, round_id: UUID) -> list[Ranked]:
        """Signups, best first; deterministic."""
        p = self._p
        rnd = await self._round(round_id)
        await require(p, actor, rnd.club_id, Permission.EDIT_EVENTS)
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        history: list[DraftPick] = []
        for r in await p.drafts.list_rounds(rnd.club_id):
            history += await p.drafts.list_picks(r.id)
        out: list[Candidate] = []
        for s in await p.drafts.list_signups(round_id):
            if s.status == "withdrawn":
                continue
            profile = await p.drafts.get_profile(s.user_id, rnd.club_id)
            data = {**(profile.answers if profile else {}), **s.answers}
            entries = await p.points.entries(rnd.club_id, s.user_id)
            out.append(
                Candidate(
                    s.user_id,
                    _strings(data.get("availability")),
                    _strings(data.get("skills")),
                    sum(
                        1
                        for h in history
                        if h.user_id == s.user_id and h.status == "completed"
                    ),
                    sum(
                        1
                        for h in history
                        if h.user_id == s.user_id and h.status == "no_show"
                    ),
                    sum(e.points for e in entries),
                )
            )
        return rank_candidates(out, Requirements(frozenset(), frozenset()))

    async def pick(
        self, actor: Actor, round_id: UUID, user_id: UUID, role: str
    ) -> DraftPick:
        """Choose a signed-up volunteer for a role."""
        p = self._p
        rnd = await self._round(round_id)
        await require(p, actor, rnd.club_id, Permission.EDIT_EVENTS)
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        if not any(
            s.user_id == user_id and s.status != "withdrawn"
            for s in await p.drafts.list_signups(round_id)
        ):
            raise DraftInvalidError(params={"field": "user_id"})
        picks = await p.drafts.list_picks(round_id)
        filled: dict[str, int] = {}
        for x in picks:
            if x.status in _TAKEN:
                filled[x.role] = filled.get(x.role, 0) + 1
        pick = DraftPick.propose(rnd, user_id, role, filled)
        await p.drafts.add_pick(pick)
        return pick

    async def invite(self, actor: Actor, pick_id: UUID) -> DraftPick:
        """Send the invitation to the picked volunteer."""
        p = self._p
        pick, rnd = await self._pick(pick_id)
        await require(p, actor, rnd.club_id, Permission.EDIT_EVENTS)
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        pick.invite()
        await p.drafts.save_pick(pick)
        await p.notifier.send(
            [
                note(
                    pick.user_id,
                    NotificationType.DRAFT_INVITE,
                    {
                        "pick_id": str(pick.id),
                        "round_id": str(rnd.id),
                        "event_id": str(rnd.event_id),
                        "club_id": str(rnd.club_id),
                        "role": pick.role,
                    },
                    f"activities:draft-invite:{pick.id}",
                )
            ]
        )
        return pick

    async def respond(self, actor: Actor, pick_id: UUID, accept: bool) -> DraftPick:
        """The volunteer answers the invitation."""
        p = self._p
        pick, rnd = await self._pick(pick_id)
        if pick.user_id != actor.user_id:
            raise PermissionDeniedError()
        await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        pick.accept() if accept else pick.decline()
        await p.drafts.save_pick(pick)
        return pick

    async def complete(self, actor: Actor, pick_id: UUID) -> DraftPick:
        """The shift was worked: points for the volunteer."""
        p = self._p
        pick, rnd = await self._pick(pick_id)
        await require(p, actor, rnd.club_id, Permission.EDIT_EVENTS)
        club = await require_capability(p, rnd.club_id, ClubCapability.DRAFTING)
        pick.complete()
        await p.drafts.save_pick(pick)
        await award(p, club, "draft_completed", pick.user_id, pick.id)
        return pick

    async def mark_no_show_due(self) -> int:
        """Two hours after an event ends, accepted no-show volunteers get -4."""
        p = self._p
        now = p.clock.now()
        marked = 0
        for pick in await p.drafts.list_picks_with_status("accepted"):
            rnd = await p.drafts.get_round(pick.round_id)
            event = await p.events.get(rnd.event_id) if rnd else None
            if (
                rnd is None
                or event is None
                or event.status == EventStatus.CANCELLED
                or now < event.ends_at + NO_SHOW_GRACE
            ):
                continue
            rsvp = await p.events.get_rsvp(event.id, pick.user_id)
            if rsvp is not None and rsvp.checked_in_at is not None:
                continue
            pick.mark_no_show()
            await p.drafts.save_pick(pick)
            await award(
                p, await load_club(p, rnd.club_id), "no_show", pick.user_id, pick.id
            )
            marked += 1
        return marked
