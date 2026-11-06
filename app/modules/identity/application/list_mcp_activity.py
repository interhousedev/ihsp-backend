"""Reads of the MCP call log: a person's own calls, every call for administrators."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.identity.application.audit_drafts import make_audit
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.audit_event import MCP_ACTIVITY_VIEWED
from app.modules.identity.ports.mcp_call_log import (
    McpCallEntry,
    McpCallFilter,
    McpToolSummary,
)
from app.modules.identity.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.notifications import AuditDraft
from app.shared.pagination import Page

PAGE_SIZE = 50
SUMMARY_DEFAULT_DAYS = 7


@dataclass(frozen=True, slots=True)
class ListMcpActivity:
    """The user's reads are scoped here; each administrator's read is audited."""

    uow_factory: UowFactory
    clock: Clock

    async def for_user(
        self,
        user_id: UUID,
        *,
        connector_id: UUID | None = None,
        tool: str | None = None,
        outcome: str | None = None,
        since: datetime | None = None,
        until: datetime | None = None,
        cursor: str | None = None,
        limit: int = PAGE_SIZE,
    ) -> Page[McpCallEntry]:
        """One page of the caller's own calls, whatever the filter names."""
        where = McpCallFilter(
            user_id=user_id,
            connector_id=connector_id,
            tool=tool,
            outcome=outcome,
            since=since,
            until=until,
        )
        async with self.uow_factory() as uow:
            return await uow.mcp_calls.search(where, cursor=cursor, limit=limit)

    async def for_admin(
        self,
        actor: Actor,
        ctx: RequestContext,
        where: McpCallFilter,
        *,
        cursor: str | None = None,
        limit: int = PAGE_SIZE,
    ) -> Page[McpCallEntry]:
        """One page of anyone's calls; the read itself goes to the audit log."""
        async with self.uow_factory() as uow:
            page = await uow.mcp_calls.search(where, cursor=cursor, limit=limit)
            uow.audit(self._viewed(actor, ctx, where, "list"))
            await uow.commit()
        return page

    async def summary(
        self,
        actor: Actor,
        ctx: RequestContext,
        since: datetime | None,
        until: datetime | None,
    ) -> list[McpToolSummary]:
        """Calls and failures per tool (default: the last 7 days), audited."""
        start = since or self.clock.now() - timedelta(days=SUMMARY_DEFAULT_DAYS)
        where = McpCallFilter(since=start, until=until)
        async with self.uow_factory() as uow:
            rows = await uow.mcp_calls.summary(where)
            uow.audit(self._viewed(actor, ctx, where, "summary"))
            await uow.commit()
        return rows

    @staticmethod
    def _viewed(
        actor: Actor, ctx: RequestContext, where: McpCallFilter, view: str
    ) -> AuditDraft:
        filters = {
            "user_id": where.user_id,
            "connector_id": where.connector_id,
            "server": where.server,
            "tool": where.tool,
            "outcome": where.outcome,
            "from": where.since.isoformat() if where.since else None,
            "to": where.until.isoformat() if where.until else None,
        }
        return make_audit(
            MCP_ACTIVITY_VIEWED,
            user_id=actor.user_id,
            ctx=ctx,
            view=view,
            filter={k: str(v) for k, v in filters.items() if v is not None},
        )
