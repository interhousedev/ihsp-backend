"""Use case: read a changed upstream object again (the Sync button, NB-8)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.readers.chat_reader import latest_ref
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceKind, SourceStatus
from app.modules.notebooks.domain.errors import SourceNotReadyError
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

SYNCABLE = (
    SourceKind.CHAT,
    SourceKind.FLASHCARD_SET,
    SourceKind.LMS_STEP,
    SourceKind.URL,
    SourceKind.LIBRARY_ITEM,
    SourceKind.LIBRARY_NOTES,
)
UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)


class SyncSource:
    """Puts a chat, flash card set, LMS step or web page back to `pending`."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, actor: Actor, notebook_id: UUID, source_id: UUID) -> Source:
        """Queue a new read; other kinds come back unchanged.

        A chat is re-snapshotted to its latest message. Old citations keep their
        snapshots, so they are not affected when the passages are replaced.

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            SourceNotReadyError: The source is still being processed.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True
            )
            if source.kind not in SYNCABLE:
                return source
            if source.status in UNFINISHED:
                raise SourceNotReadyError()
            if source.kind is SourceKind.CHAT:
                source.ref = latest_ref(source.ref)
            if source.kind is SourceKind.LMS_STEP:
                # The old revision alias would share the old text; the read sets it.
                source.ref = {k: v for k, v in source.ref.items() if k != "revision_id"}
            source.status = SourceStatus.PENDING
            source.failure = None
            source.updated_at = self.clock.now()
            await uow.sources.save(source)
            uow.after_commit(
                partial(
                    self.kicker.kick,
                    "notebooks.process_source",
                    source_id=str(source.id),
                )
            )
            await uow.commit()
        return source
