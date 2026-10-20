"""Use case: read a source's upstream text again (the Re-read button)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)


class RereadSource:
    """Puts any source back to `pending` so that its text is extracted again."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, kicker: TaskKicker
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker

    async def execute(self, actor: Actor, notebook_id: UUID, source_id: UUID) -> Source:
        """Queue a new extraction; a source already waiting or being read is returned.

        Only the owner of the notebook, or a course editor for a course workspace, may
        do this (anyone else gets the usual 404 or read-only error).

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            WorkspaceReadOnlyError: The caller may only read the course workspace.
        """
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True
            )
            if source.status in UNFINISHED:
                return source
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
