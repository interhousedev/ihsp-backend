"""Club team: positions, applications, seats and the student's public consent."""

from typing import Any
from uuid import UUID, uuid4

from app.modules.activities.application.common import (
    load_club,
    note,
    require,
)
from app.modules.activities.domain.access import Permission
from app.modules.activities.domain.errors import ActivitiesNotFoundError
from app.modules.activities.domain.team import (
    PositionApplication,
    TeamPosition,
    TeamSeat,
    public_name,
    validate_form_schema,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor
from app.shared.notifications import NotificationType


class TeamService:
    """Outsiders and members apply to positions; seats are public only with consent."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def create_position(
        self,
        actor: Actor,
        club_id: UUID,
        title: Any,
        description: Any = None,
        slots: int = 1,
        form_schema: dict[str, Any] | None = None,
        open_for_applications: bool = True,
    ) -> TeamPosition:
        """Add a position to recruit for."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_CLUB)
        await load_club(p, club_id)
        schema = form_schema if form_schema is not None else {"fields": []}
        validate_form_schema(schema)
        order = len(await p.team.list_positions(club_id))
        position = TeamPosition(
            uuid4(),
            club_id,
            title,
            description,
            max(1, slots),
            open_for_applications,
            schema,
            order,
        )
        await p.team.add_position(position)
        return position

    async def list_positions(self, club_id: UUID) -> list[TeamPosition]:
        """Positions of a club."""
        return await self._p.team.list_positions(club_id)

    async def _position(self, position_id: UUID) -> TeamPosition:
        position = await self._p.team.get_position(position_id)
        if position is None:
            raise ActivitiesNotFoundError()
        return position

    async def apply(
        self, actor: Actor, position_id: UUID, answers: dict[str, Any]
    ) -> PositionApplication:
        """Apply to an open position."""
        p = self._p
        position = await self._position(position_id)
        app = PositionApplication.submit(
            position,
            actor.user_id,
            answers,
            await p.team.count_accepted(position_id),
        )
        await p.team.add_application(app)
        return app

    async def applications(
        self, actor: Actor, position_id: UUID
    ) -> list[PositionApplication]:
        """Organizers read the applications."""
        position = await self._position(position_id)
        await require(self._p, actor, position.club_id, Permission.VIEW_MEMBERS)
        return await self._p.team.list_applications(position_id)

    async def _managed(
        self, actor: Actor, application_id: UUID
    ) -> tuple[PositionApplication, TeamPosition]:
        app = await self._p.team.get_application(application_id)
        if app is None:
            raise ActivitiesNotFoundError()
        position = await self._position(app.position_id)
        await require(self._p, actor, position.club_id, Permission.EDIT_CLUB)
        return app, position

    async def shortlist(
        self, actor: Actor, application_id: UUID
    ) -> PositionApplication:
        """Move to the short list."""
        app, _ = await self._managed(actor, application_id)
        app.shortlist()
        await self._p.team.save_application(app)
        return app

    async def reject(
        self, actor: Actor, application_id: UUID, reason: str | None = None
    ) -> PositionApplication:
        """Reject with a note; the applicant is told."""
        app, _ = await self._managed(actor, application_id)
        app.reject(reason)
        await self._p.team.save_application(app)
        await self._tell(app, "rejected")
        return app

    async def accept(self, actor: Actor, application_id: UUID) -> TeamSeat:
        """Accept: the person takes a seat, hidden until they consent."""
        p = self._p
        app, position = await self._managed(actor, application_id)
        app.accept(await p.team.count_accepted(position.id), position.slots)
        await p.team.save_application(app)
        seat = TeamSeat(
            position.id, app.user_id, p.clock.now(), None, False, False, None, []
        )
        await p.team.add_seat(seat)
        await self._tell(app, "accepted")
        return seat

    async def withdraw(self, actor: Actor, application_id: UUID) -> PositionApplication:
        """The applicant takes the application back."""
        p = self._p
        app = await p.team.get_application(application_id)
        if app is None or app.user_id != actor.user_id:
            raise ActivitiesNotFoundError()
        app.withdraw()
        await p.team.save_application(app)
        return app

    async def _tell(self, app: PositionApplication, result: str) -> None:
        await self._p.notifier.send(
            [
                note(
                    app.user_id,
                    NotificationType.POSITION_APPLICATION_RESULT,
                    {"application_id": str(app.id), "result": result},
                    f"activities:position-result:{app.id}:{result}",
                )
            ]
        )

    async def _seat(self, seat_id: UUID) -> TeamSeat:
        seat = await self._p.team.get_seat(seat_id)
        if seat is None:
            raise ActivitiesNotFoundError()
        return seat

    async def set_consent(self, actor: Actor, seat_id: UUID, granted: bool) -> TeamSeat:
        """Only the seat's own student grants or withdraws public display."""
        p = self._p
        seat = await self._seat(seat_id)
        now = p.clock.now()
        event = (
            seat.grant_consent(actor.user_id, now)
            if granted
            else seat.revoke_consent(actor.user_id, now)
        )
        await p.team.save_seat(seat)
        await p.team.add_consent_event(event)
        return seat

    async def set_public(self, actor: Actor, seat_id: UUID, public: bool) -> TeamSeat:
        """The manager's publish flag; shown only with the student's consent too."""
        p = self._p
        seat = await self._seat(seat_id)
        position = await self._position(seat.position_id)
        await require(p, actor, position.club_id, Permission.EDIT_CLUB)
        seat.public = public
        await p.team.save_seat(seat)
        return seat

    async def public_team(self, club_id: UUID) -> list[dict[str, Any]]:
        """Seats visible to anyone: published, consented, not ended."""
        p = self._p
        now = p.clock.now()
        positions = {x.id: x for x in await p.team.list_positions(club_id)}
        rows = []
        for seat in await p.team.list_seats(club_id):
            if not seat.is_publicly_visible(now):
                continue
            first, _, last = (await p.users.display_name(seat.user_id)).partition(" ")
            rows.append(
                {
                    "name": public_name(first, last),
                    "position": positions[seat.position_id].title,
                    "bio": seat.bio,
                    "photo_url": seat.photo_url,
                }
            )
        return rows
