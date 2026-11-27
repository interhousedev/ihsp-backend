"""Club planner board."""

from datetime import datetime
from uuid import UUID

from app.modules.activities.application.common import load_club, require
from app.modules.activities.domain.access import Permission
from app.modules.activities.domain.errors import ActivitiesNotFoundError, Conflict
from app.modules.activities.domain.planner import (
    PlannerItem,
    PlannerStatus,
    completion_ratio,
)
from app.modules.activities.ports.bundle import Ports
from app.shared.actor import Actor


class PlannerMoveError(Conflict):
    """A finished item can only be reopened to doing."""


class PlannerService:
    """Organizers plan ideas, tasks and milestones."""

    def __init__(self, ports: Ports) -> None:
        """Keep the ports."""
        self._p = ports

    async def add(
        self,
        actor: Actor,
        club_id: UUID,
        title: str,
        kind: str = "task",
        body: str = "",
        assignee_id: UUID | None = None,
        due_at: datetime | None = None,
        event_id: UUID | None = None,
        term: str = "",
    ) -> PlannerItem:
        """Put an item in the backlog."""
        p = self._p
        await require(p, actor, club_id, Permission.EDIT_EVENTS)
        await load_club(p, club_id)
        item = PlannerItem(
            club_id,
            kind,
            title,
            body,
            assignee_id,
            due_at,
            PlannerStatus.BACKLOG,
            event_id,
            term,
        )
        await p.planner.add(item)
        return item

    async def move(
        self, actor: Actor, item_id: UUID, status: PlannerStatus
    ) -> PlannerItem:
        """Move to another column."""
        p = self._p
        item = await p.planner.get(item_id)
        if item is None:
            raise ActivitiesNotFoundError()
        await require(p, actor, item.club_id, Permission.EDIT_EVENTS)
        try:
            item.move(PlannerStatus(status))
        except ValueError as exc:
            raise PlannerMoveError() from exc
        await p.planner.save(item)
        return item

    async def board(self, actor: Actor, club_id: UUID) -> dict[str, object]:
        """Items of the club and the share done."""
        p = self._p
        await require(p, actor, club_id, Permission.VIEW_MEMBERS)
        items = await p.planner.list(club_id)
        return {"items": items, "completion": completion_ratio(items)}
