"""List the caller's files, newest first, with cursor pagination."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.contracts.files import FilePurpose
from app.shared.pagination import decode_cursor, encode_cursor

DEFAULT_LIMIT = 20
MAX_LIMIT = 100


@dataclass(frozen=True, slots=True)
class FilePage:
    """One page of file views and the cursor of the next page."""

    items: list[FileView]
    next_cursor: str | None


def _after(cursor: str | None) -> tuple[datetime, UUID] | None:
    data = decode_cursor(cursor)
    if data is None:
        return None
    return datetime.fromisoformat(data["t"]), UUID(data["id"])


class ListMyFiles:
    """My files page (WEB-21)."""

    def __init__(self, *, uow_factory: UowFactory, views: FileViewBuilder) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._views = views

    async def execute(
        self,
        actor: Actor,
        *,
        purpose: FilePurpose | None = None,
        cursor: str | None = None,
        limit: int = DEFAULT_LIMIT,
    ) -> FilePage:
        """Return up to ``limit`` files and a cursor when there are more."""
        size = max(1, min(limit, MAX_LIMIT))
        async with self._uow_factory() as uow:
            rows = await uow.files.list_for_owner(
                actor.user_id, purpose=purpose, after=_after(cursor), limit=size + 1
            )
        page, more = rows[:size], len(rows) > size
        next_cursor = None
        if more:
            last = page[-1]
            next_cursor = encode_cursor(
                {"t": last.created_at.isoformat(), "id": str(last.id)}
            )
        return FilePage(items=await self._views.build(page), next_cursor=next_cursor)
