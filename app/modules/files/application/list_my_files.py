"""List the caller's files, newest first, with cursor pagination."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.files.application.file_views import FileView, FileViewBuilder
from app.modules.files.domain.list_filters import (
    FileSort,
    FileTypeFilter,
    content_types_of,
)
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
        q: str | None = None,
        type: FileTypeFilter | None = None,  # noqa: A002
        sort: FileSort = "recent",
        page: int | None = None,
        page_size: int | None = None,
    ) -> FilePage:
        """Return up to ``limit`` files and a cursor when there are more.

        With `page` the list is offset-paged (`page_size` rows, 1-based) and
        `next_cursor` is the number of the next page.
        """
        paged = page is not None
        size = max(1, min(page_size if paged and page_size else limit, MAX_LIMIT))
        number = max(1, page or 1)
        async with self._uow_factory() as uow:
            rows = await uow.files.list_for_owner(
                actor.user_id,
                purpose=purpose,
                after=None if paged else _after(cursor),
                limit=size + 1,
                name_query=(q or "").strip() or None,
                content_types=content_types_of(type),
                oldest_first=sort == "older",
                offset=(number - 1) * size if paged else 0,
            )
        page_rows, more = rows[:size], len(rows) > size
        if paged:
            return FilePage(
                items=await self._views.build(page_rows),
                next_cursor=str(number + 1) if more else None,
            )
        next_cursor = None
        if more:
            last = page_rows[-1]
            next_cursor = encode_cursor(
                {"t": last.created_at.isoformat(), "id": str(last.id)}
            )
        return FilePage(
            items=await self._views.build(page_rows), next_cursor=next_cursor
        )
