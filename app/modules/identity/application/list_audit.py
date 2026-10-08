"""GET /v1/admin/audit: the audit log with filters."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.identity.application.audit_page import AuditPage, with_actors
from app.modules.identity.ports.unit_of_work import UowFactory


@dataclass(frozen=True, slots=True)
class ListAudit:
    """Newest first; filter by user, event type and period."""

    uow_factory: UowFactory

    async def execute(
        self,
        *,
        user_id: UUID | None,
        type: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> AuditPage:
        """Return one page of events."""
        async with self.uow_factory() as uow:
            page = await uow.audit_events.search(
                user_id=user_id,
                type=type,
                since=since,
                until=until,
                cursor=cursor,
                limit=limit,
            )
            return await with_actors(uow, page)
