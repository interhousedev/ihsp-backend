"""List EMIS sync runs for the monitoring page (ADM-14)."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.shared.actor import Actor, Role
from app.shared.pagination import Page, decode_cursor, encode_cursor

DEFAULT_LIMIT = 20


class ListSyncRuns:
    """Returns sync runs newest first, one cursor page at a time."""

    def __init__(self, *, uow_factory: MarksUowFactory) -> None:
        """Store the unit of work factory."""
        self._uow_factory = uow_factory

    async def execute(
        self, actor: Actor, cursor: str | None, limit: int = DEFAULT_LIMIT
    ) -> Page[dict[str, Any]]:
        """Return a page of `SyncRunItem` dicts."""
        actor.require(Role.ADMIN)
        position = _position(decode_cursor(cursor))
        async with self._uow_factory() as uow:
            rows = await uow.sync_runs.list_page(before=position, limit=limit + 1)
        page, extra = rows[:limit], rows[limit:]
        items = [
            {
                "id": run.id,
                "started_at": run.started_at,
                "finished_at": run.finished_at,
                "status": run.status,
                "stats": run.stats,
            }
            for run in page
        ]
        next_cursor = None
        if extra and page:
            last = page[-1]
            next_cursor = encode_cursor(
                {"t": last.started_at.isoformat(), "id": str(last.id)}
            )
        return Page[dict[str, Any]](items=items, next_cursor=next_cursor)


def _position(data: dict[str, Any] | None) -> tuple[dt.datetime, UUID] | None:
    if data is None:
        return None
    return dt.datetime.fromisoformat(data["t"]), UUID(data["id"])
