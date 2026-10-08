"""GET /v1/id/me/activity: the caller's own security log (UF-ID-14)."""

from dataclasses import dataclass

from app.modules.identity.application.audit_page import AuditPage, with_actors
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor


@dataclass(frozen=True, slots=True)
class ListActivity:
    """Newest events first with cursor pagination."""

    uow_factory: UowFactory

    async def execute(
        self, actor: Actor, *, cursor: str | None, limit: int
    ) -> AuditPage:
        """Return one page of the caller's events."""
        async with self.uow_factory() as uow:
            page = await uow.audit_events.search(
                user_id=actor.user_id,
                type=None,
                since=None,
                until=None,
                cursor=cursor,
                limit=limit,
            )
            return await with_actors(uow, page)
