"""FilesViews over the files module: expiry dates and the global file search."""

import datetime as dt
from uuid import UUID

from app.bootstrap.adapters.composition.actors import student_actor
from app.interfaces.http.v1.composition.ports import JsonObject
from app.interfaces.http.v1.files.mapping import to_file_item
from app.modules.files.application.file_views import FileView
from app.modules.files.application.list_my_files import ListMyFiles
from app.modules.files.domain.status import FileStatus
from app.shared.contracts.files import FilesApi

PAGE_SIZE = 100
# Storage quotas keep an owner far below this many files (pages of PAGE_SIZE).
MAX_PAGES = 50


class FilesViewsAdapter:
    """Composition <- files: what `FilesApi` lacks for alerts and search."""

    def __init__(self, list_my_files: ListMyFiles, files: FilesApi) -> None:
        """Keep the owner's file list use case and the public files API."""
        self._list_my_files = list_my_files
        self._files = files

    async def expiry_dates(self, owner_id: UUID, until: dt.date) -> list[dt.date]:
        """Return `expires_on` of the owner's ready files due on or before `until`."""
        views = await self._ready_views(owner_id)
        return sorted(
            view.expires_on
            for view in views
            if view.expires_on is not None and view.expires_on <= until
        )

    async def search_files(
        self, owner_id: UUID, query: str, limit: int
    ) -> list[JsonObject]:
        """Return `FileItem` dicts: text matches first, then name matches.

        The text hits come from `FilesApi.search_text`; the name match is a
        case-insensitive substring test over the owner's ready files.
        """
        hits = await self._files.search_text(owner_id, query, limit)
        by_id = {view.file.id: view for view in await self._ready_views(owner_id)}
        found = [by_id[hit["file_id"]] for hit in hits if hit["file_id"] in by_id]
        needle = query.strip().casefold()
        named = [
            view
            for view in by_id.values()
            if needle and needle in view.file.name.casefold()
        ]
        unique = {view.file.id: view for view in [*found, *named]}
        return [
            to_file_item(view).model_dump(mode="json")
            for view in list(unique.values())[:limit]
        ]

    async def _ready_views(self, owner_id: UUID) -> list[FileView]:
        """Return every ready file of the owner, newest first."""
        actor = student_actor(owner_id)
        views: list[FileView] = []
        cursor: str | None = None
        for _ in range(MAX_PAGES):
            page = await self._list_my_files.execute(
                actor, cursor=cursor, limit=PAGE_SIZE
            )
            views.extend(v for v in page.items if v.file.status == FileStatus.READY)
            cursor = page.next_cursor
            if cursor is None:
                break
        return views
