"""Job `notebooks.sweep_sources` (daily): files that are gone, upstream changes."""

from collections import defaultdict
from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime
from functools import partial
from typing import Final
from uuid import UUID

from app.modules.notebooks.application.notebook_state import sources_changed
from app.modules.notebooks.application.readers.registry import SourceReaders
from app.modules.notebooks.application.readers.unavailable import mark_unavailable
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind, SourceStatus
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.base_error import BaseError
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

log = structlog.get_logger(__name__)

BATCH: Final = 100
FILE_KINDS = (SourceKind.FILE, SourceKind.LESSON_RESOURCE)
LIBRARY_KINDS = (SourceKind.LIBRARY_ITEM, SourceKind.LIBRARY_NOTES)
VERSIONED_KINDS = (
    SourceKind.CHAT,
    SourceKind.FLASHCARD_SET,
    SourceKind.LMS_STEP,
    SourceKind.LIBRARY_NOTES,
)
WITH_TEXT = (SourceStatus.READY, SourceStatus.STALE)
WITHOUT_TEXT = (SourceStatus.UNAVAILABLE,)

Mark = Callable[[NotebooksUnitOfWork, Source, datetime], Awaitable[None]]
Check = Callable[[Sequence[Source]], Awaitable[set[UUID]]]


async def _mark_stale(uow: NotebooksUnitOfWork, source: Source, now: datetime) -> None:
    """Offer a re-sync: the text is still usable."""
    source.status = SourceStatus.STALE
    source.updated_at = now
    await uow.sources.save(source)


async def _mark_withdrawn(
    uow: NotebooksUnitOfWork, source: Source, now: datetime
) -> None:
    """The library no longer lets the owner use the item (held, taken down)."""
    await mark_unavailable(uow, source, now, SourceFailure.FORBIDDEN)


class SweepSources:
    """Marks sources whose file is gone `unavailable` and outdated ones `stale`.

    Library sources are checked against the library every day: a held or taken-down
    book turns them `unavailable`, and a restored one is read again.
    """

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        readers: SourceReaders,
        kicker: TaskKicker | None = None,
    ) -> None:
        """Store the collaborators; `kicker` starts the re-reading of restored books."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.readers = readers
        self.kicker = kicker

    async def execute(self) -> int:
        """Run the checks; return how many sources changed."""
        gone = await self._sweep(
            FILE_KINDS, WITH_TEXT, self.readers.unavailable_files, mark_unavailable
        )
        withdrawn = await self._sweep(
            LIBRARY_KINDS, WITH_TEXT, self.readers.unavailable_library, _mark_withdrawn
        )
        restored = await self._sweep(
            LIBRARY_KINDS, WITHOUT_TEXT, self.readers.available_library, self._requeue
        )
        outdated = await self._sweep(
            VERSIONED_KINDS, (SourceStatus.READY,), self._outdated, _mark_stale
        )
        if gone or withdrawn or restored or outdated:
            log.info(
                "notebooks_sources_swept",
                unavailable=gone + withdrawn,
                requeued=restored,
                stale=outdated,
            )
        return gone + withdrawn + restored + outdated

    async def _requeue(
        self, uow: NotebooksUnitOfWork, source: Source, now: datetime
    ) -> None:
        """The item is readable again: back to `pending`, read after the commit."""
        source.status = SourceStatus.PENDING
        source.failure = None
        source.updated_at = now
        await uow.sources.save(source)
        if self.kicker is not None:
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )

    async def _sweep(
        self,
        kinds: Sequence[SourceKind],
        statuses: Sequence[SourceStatus],
        check: Check,
        mark: Mark,
    ) -> int:
        """Walk the sources by id in batches; `check` picks those to change."""
        changed = 0
        after: UUID | None = None
        while True:
            async with self.uow_factory() as uow:
                batch = await uow.sources.list_for_sweep(
                    kinds, statuses, after_id=after, limit=BATCH
                )
            if not batch:
                return changed
            after = batch[-1].id
            flagged = await check(batch)
            changed += await self._apply(
                [s for s in batch if s.id in flagged], statuses, mark
            )

    async def _outdated(self, sources: Sequence[Source]) -> set[UUID]:
        """Ids of the sources whose upstream version differs from the snapshot."""
        found: set[UUID] = set()
        for source in sources:
            try:
                version = await self.readers.current_version(source)
            except BaseError as error:
                log.warning(
                    "notebooks_version_check_failed",
                    source_id=str(source.id),
                    error=error.code,
                )
                continue
            if version is not None and version != source.upstream_version:
                found.add(source.id)
        return found

    async def _apply(
        self, flagged: Sequence[Source], statuses: Sequence[SourceStatus], mark: Mark
    ) -> int:
        """Change the flagged sources, notebook by notebook, under the row locks."""
        by_notebook: dict[UUID, list[UUID]] = defaultdict(list)
        for source in flagged:
            by_notebook[source.notebook_id].append(source.id)
        changed = 0
        for notebook_id, source_ids in by_notebook.items():
            changed += await self._apply_to_notebook(
                notebook_id, source_ids, statuses, mark
            )
        return changed

    async def _apply_to_notebook(
        self,
        notebook_id: UUID,
        source_ids: Sequence[UUID],
        statuses: Sequence[SourceStatus],
        mark: Mark,
    ) -> int:
        now = self.clock.now()
        changed = 0
        async with self.uow_factory() as uow:
            notebook = await uow.notebooks.get_for_update(notebook_id)
            if notebook is None:
                return 0
            for source_id in source_ids:
                source = await uow.sources.get_for_update(source_id)
                if source is not None and source.status in statuses:
                    await mark(uow, source, now)
                    changed += 1
            if changed:
                await sources_changed(uow, notebook, now)
                await uow.commit()
        return changed
