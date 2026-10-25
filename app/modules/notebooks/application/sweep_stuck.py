"""Job `notebooks.sweep_stuck`: unstick sources, outputs and summaries (§ 4.5)."""

from collections.abc import Awaitable, Callable, Sequence
from datetime import datetime, timedelta
from functools import partial
from typing import TypeVar
from uuid import UUID

from app.modules.notebooks.application.extract_source_vision import (
    STARTED_KEY,
)
from app.modules.notebooks.application.extract_source_vision import TASK as VISION_TASK
from app.modules.notebooks.application.quota import QuotaService
from app.modules.notebooks.domain.entities import (
    Artifact,
    ArtifactError,
    Notebook,
    Source,
)
from app.modules.notebooks.domain.enums import (
    ArtifactKind,
    ArtifactStatus,
    SourceKind,
    SourceStatus,
    SummaryStatus,
)
from app.modules.notebooks.domain.limits import (
    STUCK_ARTIFACT_MINUTES,
    STUCK_SOURCE_MINUTES,
)
from app.modules.notebooks.ports.unit_of_work import NotebooksUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.tasks import TaskKicker

import structlog

BATCH = 100
MAX_BATCHES = 20  # at most 2000 rows of a kind per run
STUCK_SUMMARY_MINUTES = 10
VISION_MINUTES = 10  # a model read of a scanned file gets this long before a re-kick
UNFINISHED = (SourceStatus.PENDING, SourceStatus.PROCESSING)
log = structlog.get_logger(__name__)

Row = TypeVar("Row")


class SweepStuck:
    """Re-kicks lost jobs and ends outputs that never finished (cron every 10 min)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        kicker: TaskKicker,
        quota: QuotaService,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.kicker = kicker
        self.quota = quota

    async def execute(self) -> dict[str, int]:
        """Run the four sweeps and return how many rows each one touched.

        Keys: `sources` (re-kicked), `artifacts_failed` (timed out),
        `artifacts_requeued` (re-kicked) and `summaries` (back to stale). Every row
        it touches gets a fresh `updated_at`, so the next run leaves it alone until
        it has been stuck for another full period.
        """
        now = self.clock.now()
        source_cutoff = now - timedelta(minutes=STUCK_SOURCE_MINUTES)
        artifact_cutoff = now - timedelta(minutes=STUCK_ARTIFACT_MINUTES)
        summary_cutoff = now - timedelta(minutes=STUCK_SUMMARY_MINUTES)
        counts = {
            "sources": await self._sweep(
                lambda uow: uow.sources.stuck_processing(source_cutoff, BATCH),
                partial(self._rekick_source, now, source_cutoff),
            ),
            "artifacts_failed": await self._sweep(
                lambda uow: uow.artifacts.stuck_generating(artifact_cutoff, BATCH),
                partial(self._time_out_artifact, now, artifact_cutoff),
            ),
            "artifacts_requeued": await self._sweep(
                lambda uow: uow.artifacts.stuck_queued(artifact_cutoff, BATCH),
                partial(self._rekick_artifact, now, artifact_cutoff),
            ),
            "summaries": await self._sweep(
                lambda uow: uow.notebooks.stuck_summaries(summary_cutoff, BATCH),
                partial(self._reset_summary, now),
            ),
        }
        if any(counts.values()):
            log.info("notebooks_swept", **counts)
        return counts

    async def _sweep(
        self,
        find: Callable[[NotebooksUnitOfWork], Awaitable[Sequence[Row]]],
        handle: Callable[[NotebooksUnitOfWork, Row], Awaitable[bool]],
    ) -> int:
        """Handle the rows `find` returns, batch by batch; count those it touched."""
        total = 0
        for _ in range(MAX_BATCHES):
            async with self.uow_factory() as uow:
                found = await find(uow)
                for row in found:
                    if await handle(uow, row):
                        total += 1
                await uow.commit()
            if len(found) < BATCH:
                break
        return total

    async def _rekick_source(
        self,
        now: datetime,
        cutoff: datetime,
        uow: NotebooksUnitOfWork,
        candidate: Source,
    ) -> bool:
        """Start `process_source` again (the row is re-read under its lock)."""
        source = await uow.sources.get_for_update(candidate.id)
        if (
            source is None
            or source.status not in UNFINISHED
            or source.updated_at >= cutoff
        ):
            return False
        task = "notebooks.process_source"
        if source.kind is SourceKind.FILE and STARTED_KEY in source.ref:
            started = datetime.fromisoformat(str(source.ref[STARTED_KEY]))
            if started >= now - timedelta(minutes=VISION_MINUTES):
                return False  # the model is still reading this scanned file
            task = VISION_TASK  # its read was lost: start the read again
        source.updated_at = now
        await uow.sources.save(source)
        uow.after_commit(partial(self.kicker.kick, task, source_id=str(source.id)))
        return True

    async def _time_out_artifact(
        self,
        now: datetime,
        cutoff: datetime,
        uow: NotebooksUnitOfWork,
        candidate: Artifact,
    ) -> bool:
        """Fail an output that has been generating for too long; it is not counted."""
        artifact = await uow.artifacts.get_for_update(candidate.id)
        if (
            artifact is None
            or artifact.status is not ArtifactStatus.GENERATING
            or artifact.started_at is None
            or artifact.started_at >= cutoff
        ):
            return False
        artifact.status = ArtifactStatus.FAILED
        artifact.error = ArtifactError(
            code="timeout", message_key="notebooks-artifact-error-timeout"
        )
        artifact.finished_at = now
        artifact.updated_at = now
        await uow.artifacts.save(artifact)
        notebook = await uow.notebooks.get(artifact.notebook_id)
        course = notebook is not None and notebook.is_course_workspace
        uow.after_commit(
            partial(
                self._free_slot,
                artifact.charged_to,
                artifact.id,
                artifact.kind,
                course=course,
            )
        )
        return True

    async def _free_slot(
        self, user_id: UUID, artifact_id: UUID, kind: ArtifactKind, *, course: bool
    ) -> None:
        """The output no longer runs and a timeout is not counted in the quota."""
        quota = self.quota.pool(course)
        await quota.finished(user_id, artifact_id)
        await quota.release(user_id, kind)

    async def _rekick_artifact(
        self,
        now: datetime,
        cutoff: datetime,
        uow: NotebooksUnitOfWork,
        candidate: Artifact,
    ) -> bool:
        """Start `generate_artifact` again for an output that stayed queued."""
        artifact = await uow.artifacts.get_for_update(candidate.id)
        if (
            artifact is None
            or artifact.status is not ArtifactStatus.QUEUED
            or artifact.deleted_at is not None
            or artifact.updated_at >= cutoff
        ):
            return False
        artifact.updated_at = now
        await uow.artifacts.save(artifact)
        uow.after_commit(
            partial(
                self.kicker.kick,
                "notebooks.generate_artifact",
                artifact_id=str(artifact.id),
            )
        )
        return True

    async def _reset_summary(
        self, now: datetime, uow: NotebooksUnitOfWork, notebook: Notebook
    ) -> bool:
        """Make a summary stuck in `building` due again (the row is already locked)."""
        notebook.summary_status = SummaryStatus.STALE
        notebook.summary_due_at = now
        notebook.updated_at = now
        await uow.notebooks.save(notebook)
        return True
