"""Use case: read a source's upstream text again (the Re-read button)."""

from functools import partial
from uuid import UUID

from app.modules.notebooks.application.access import load_notebook, load_source
from app.modules.notebooks.application.extract_source_vision import TASK, vision_started
from app.modules.notebooks.domain.entities import Source
from app.modules.notebooks.domain.enums import SourceFailure, SourceKind, SourceStatus
from app.modules.notebooks.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.rate_limit import RateLimiter
from app.shared.tasks import TaskKicker

UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)
REREADS_PER_HOUR = 20  # each re-read is a fresh extraction and may call a paid reader


class RereadSource:
    """Puts any source back to `pending` so that its text is extracted again."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        kicker: TaskKicker,
        rate_limiter: RateLimiter,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker
        self.rate_limiter = rate_limiter

    async def execute(self, actor: Actor, notebook_id: UUID, source_id: UUID) -> Source:
        """Queue a new extraction; a source already waiting or being read is returned.

        Only the owner of the notebook, or a course editor for a course workspace, may
        do this (anyone else gets the usual 404 or read-only error).

        Raises:
            NotebookNotFoundError: Notebook or source is not the caller's.
            WorkspaceReadOnlyError: The caller may only read the course workspace.
            RateLimitedError: The caller re-read too many sources in the last hour.
        """
        await self.rate_limiter.hit(
            f"nb-reread:{actor.user_id}",
            limit=REREADS_PER_HOUR,
            window_seconds=3600,
        )
        async with self.uow_factory() as uow:
            await load_notebook(uow, actor.user_id, notebook_id, for_update=True)
            source = await load_source(
                uow, actor.user_id, notebook_id, source_id, for_update=True
            )
            if source.status in UNFINISHED:
                return source
            # A scanned file has no text layer: the model reads it instead.
            vision = (
                source.kind is SourceKind.FILE
                and source.failure is SourceFailure.NO_TEXT
            )
            now = self.clock.now()
            source.status = SourceStatus.PROCESSING if vision else SourceStatus.PENDING
            source.failure = None
            source.updated_at = now
            if vision:
                source.ref = {**source.ref, **vision_started(now)}
            await uow.sources.save(source)
            task = TASK if vision else "notebooks.process_source"
            uow.after_commit(partial(self.kicker.kick, task, source_id=str(source.id)))
            await uow.commit()
        return source
