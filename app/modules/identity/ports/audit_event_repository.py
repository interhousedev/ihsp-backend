"""Port: reading audit events (writing goes through the unit of work)."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.identity.domain.audit_event import AuditEventRecord
from app.shared.pagination import Page


class AuditEventRepository(Protocol):
    """Reads audit events, newest first."""

    async def search(
        self,
        *,
        user_id: UUID | None,
        type: str | None,
        since: datetime | None,
        until: datetime | None,
        cursor: str | None,
        limit: int,
    ) -> Page[AuditEventRecord]:
        """Filter events and return one page."""
        ...

    async def recent_for_user(
        self, user_id: UUID, limit: int
    ) -> list[AuditEventRecord]:
        """The latest events of a user."""
        ...
