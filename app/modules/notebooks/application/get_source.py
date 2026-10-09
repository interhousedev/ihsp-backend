"""Use case: open one source; a file that is gone is noticed here too (FILE-6)."""

from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.readers.unavailable import mark_unavailable
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

WITH_TEXT = (SourceStatus.READY, SourceStatus.STALE)


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
