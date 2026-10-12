"""Use case: open one source; a file that is gone is noticed here too (FILE-6)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Literal
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.file_reader import file_id_of
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.readers.unavailable import mark_unavailable
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.domain.errors import NotebookNotFoundError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FileRef

WITH_TEXT = (SourceStatus.READY, SourceStatus.STALE)
FILE_URL_TTL_SECONDS = 60  # the usual lifetime of a presigned download URL

Disposition = Literal["inline", "attachment"]


@dataclass(frozen=True, slots=True)
class SourceFileUrl:
    """A short-lived URL of the file behind a source and when it stops working."""

    url: str
    expires_at: datetime


class GetSource:
    """Reads a source; drops its text first when the file behind it was deleted."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, readers: SourceReaders
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.readers = readers

    async def execute(self, actor: Actor, notebook_id: UUID, source_id: UUID) -> Source:
        """Return the source.

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
        """
        async with self.uow_factory() as uow:
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, write=False
            )
        if source.status not in WITH_TEXT or not self.readers.is_file_backed(source):
            return source
        if source.id not in await self.readers.unavailable_files([source]):
            return source
        return await self._drop_text(actor, notebook_id, source_id)

    async def file_of(self, source: Source) -> FileRef | None:
        """The uploaded file behind a `file` source or a file-based lesson material.

        Reading it goes with the notebook access already checked for the source, so
        a shared notebook shows the file to every member. Deleted files give None.
        """
        if not self.readers.is_file_backed(source):
            return None
        file_id = file_id_of(source)
        if file_id is None:
            return None
        ref = await self.readers.file_reader.files.get(file_id)
        return None if ref is None or ref.status == "deleted" else ref

    async def file_url(
        self,
        actor: Actor,
        notebook_id: UUID,
        source_id: UUID,
        disposition: Disposition | None = None,
    ) -> SourceFileUrl:
        """A presigned URL of the file behind the source (access = notebook access).

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's, or the
                source has no file (any more).
        """
        async with self.uow_factory() as uow:
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, write=False
            )
        ref = await self.file_of(source)
        if ref is None:
            raise NotebookNotFoundError()
        inline = None if disposition is None else disposition == "inline"
        url = await self.readers.file_reader.files.download_url(
            ref.id, inline=inline, ttl_seconds=FILE_URL_TTL_SECONDS
        )
        expires_at = self.clock.now() + timedelta(seconds=FILE_URL_TTL_SECONDS)
        return SourceFileUrl(url=url, expires_at=expires_at)

    async def _drop_text(
        self, actor: Actor, notebook_id: UUID, source_id: UUID
    ) -> Source:
        """Mark the source `unavailable` under the locks (once; repeats are no-ops)."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            notebook = await load_notebook(
                uow, actor.user_id, notebook_id, for_update=True, write=False
            )
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True, write=False
            )
            if source.status in WITH_TEXT:
                await mark_unavailable(uow, source, now)
                await sources_changed(uow, notebook, now)
                await uow.commit()
        return source
