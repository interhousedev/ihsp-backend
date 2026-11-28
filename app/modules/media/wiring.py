"""Builds the media module (container.media)."""

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.media.application.media_job import (
    CancelMediaJob,
    EnqueueMediaJob,
    GetMediaJob,
    ListMediaJobs,
    RetryMediaJob,
    RunMediaJob,
)
from app.modules.media.infrastructure.fakes import FakeSpeech, FakeVideo
from app.modules.media.infrastructure.repositories.sql import (
    SqlMediaJobStore,
    SqlMediaLimits,
)
from app.modules.media.ports.media import MediaFiles, OwnerAccess
from app.shared.contracts.material_sink import MaterialSink
from app.shared.contracts.speech import SpeechSynthesizer
from app.shared.contracts.teaching_scope import TeachingScope
from app.shared.wiring import ModuleDeps


class _LiveLimits(SqlMediaLimits):
    """The weekly allowance follows the limits in force (admin overrides)."""

    def __init__(self, deps: ModuleDeps) -> None:
        """Start from the database; the allowance is read per call."""
        super().__init__(deps.sessionmaker, deps.clock, 0)
        self._deps = deps

    async def used_this_week(self, owner_id: UUID) -> int:
        """Refresh the allowance, then count the week's jobs."""
        limit = (await self._deps.effective_limits.current()).media_jobs_per_week
        self.media_jobs_per_week = 10**9 if limit < 0 else limit
        return await super().used_this_week(owner_id)


class _Kicker:
    """Adapts the shared kicker (keyword arguments) to the media port."""

    def __init__(self, deps: ModuleDeps) -> None:
        self._kicker = deps.kicker

    async def kick(self, task: str, *args: Any, queue: str = "default") -> None:
        """One broker stream serves every queue name today."""
        await self._kicker.kick(task, job_id=args[0])


@dataclass(slots=True)
class MediaServices:
    """Use cases of the media module."""

    enqueue: EnqueueMediaJob
    run: RunMediaJob
    get: GetMediaJob
    list: ListMediaJobs
    retry: RetryMediaJob
    cancel: CancelMediaJob
    store: SqlMediaJobStore


def build(
    deps: ModuleDeps,
    *,
    files: MediaFiles,
    notebook_sink: MaterialSink,
    access: OwnerAccess,
    scope: TeachingScope,
    synthesizer: SpeechSynthesizer | None = None,
) -> MediaServices:
    """Wire the module; speech and video are the fakes until a provider is set."""
    store = SqlMediaJobStore(deps.sessionmaker)
    limits = _LiveLimits(deps)
    kicker = _Kicker(deps)
    return MediaServices(
        enqueue=EnqueueMediaJob(store, kicker, deps.clock, limits, scope),
        run=RunMediaJob(
            store,
            synthesizer or FakeSpeech(),
            FakeVideo(),
            files,
            notebook_sink,
            access,
        ),
        get=GetMediaJob(store),
        list=ListMediaJobs(store),
        retry=RetryMediaJob(store, kicker),
        cancel=CancelMediaJob(store),
        store=store,
    )
