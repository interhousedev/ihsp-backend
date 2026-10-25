"""Daily output quotas and the limit of outputs generating at once (§ 3.6)."""

from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from uuid import UUID

from app.modules.notebooks.domain.enums import ArtifactKind
from app.modules.notebooks.domain.errors import BusyError, QuotaExceededError
from app.modules.notebooks.ports.quota_store import QuotaStore
from app.settings import Settings
from app.shared.clock import TASHKENT, Clock, local_today
from app.shared.limits import ActorLimits, LimitsProvider, StaticLimits

TOTAL = "artifacts"  # the counter of outputs of every kind


@dataclass(frozen=True, slots=True)
class QuotaPart:
    """How many outputs of a kind were requested today, the limit and the reset."""

    used: int
    limit: int | None  # None: unlimited (staff)
    resets_at: datetime


class QuotaService:
    """Counts outputs per kind and day and the outputs that are running.

    Two pools like the budget: students' notebooks and course workspaces (`pool`);
    an output is counted for the user who asked for it.
    """

    def __init__(
        self,
        store: QuotaStore,
        clock: Clock,
        settings: Settings,
        *,
        for_course: bool = False,
        course: "QuotaService | None" = None,
        limits: LimitsProvider | None = None,
    ) -> None:
        """Store the counters, the clock and the settings.

        `for_course` makes this the course staff pool (`lms_ai_artifacts_per_day`
        outputs a day, unlimited for staff); `course` is the pool of course workspaces.
        The daily limits come from the provider (overrides, the student's extension).
        """
        self.store = store
        self.clock = clock
        self.settings = settings
        self.for_course = for_course
        self.course = course
        self.limits = limits or StaticLimits(settings.limits)

    def pool(self, course: bool) -> "QuotaService":
        """The pool of a course workspace (`course=True`) or of a student notebook."""
        return self.course if course and self.course is not None else self

    async def _view(self, user_id: UUID) -> ActorLimits:
        return await self.limits.for_user(
            user_id, unlimited=True if self.for_course else None
        )

    def limit_of(self, kind: str, view: ActorLimits) -> int | None:
        """The daily limit of a counter; None means unlimited."""
        artifacts: int | None = (
            view.lms_ai_artifacts_per_day
            if self.for_course
            else view.nb_artifacts_per_day
        )
        return {
            TOTAL: artifacts,
            ArtifactKind.AUDIO_OVERVIEW.value: view.nb_audio_per_day,
            ArtifactKind.SLIDES.value: view.nb_slides_per_day,
            ArtifactKind.INFOGRAPHIC.value: view.nb_infographics_per_day,
        }.get(kind, artifacts)

    def _midnight(self) -> datetime:
        tomorrow = local_today(self.clock) + timedelta(days=1)
        return datetime.combine(tomorrow, time.min, tzinfo=TASHKENT).astimezone(UTC)

    def counters_for(self, kind: ArtifactKind) -> list[str]:
        """The counters a request of this kind uses: the total and its own."""
        own = {
            ArtifactKind.AUDIO_OVERVIEW,
            ArtifactKind.SLIDES,
            ArtifactKind.INFOGRAPHIC,
        }
        return [TOTAL, kind.value] if kind in own else [TOTAL]

    async def snapshot(self, user_id: UUID) -> dict[str, QuotaPart]:
        """Today's usage of the four counters of `NotebookUsage.quotas`."""
        day = local_today(self.clock)
        reset = self._midnight()
        view = await self._view(user_id)
        names = [
            TOTAL,
            ArtifactKind.AUDIO_OVERVIEW.value,
            ArtifactKind.SLIDES.value,
            ArtifactKind.INFOGRAPHIC.value,
        ]
        return {
            name: QuotaPart(
                await self.store.used(user_id, day, name),
                self.limit_of(name, view),
                reset,
            )
            for name in names
        }

    async def reserve(
        self, user_id: UUID, kind: ArtifactKind, artifact_id: UUID
    ) -> None:
        """Count a request: raise `QuotaExceededError` or `BusyError`, else reserve.

        Nothing stays counted when it raises.
        """
        day = local_today(self.clock)
        view = await self._view(user_id)
        for name in self.counters_for(kind):
            used = await self.store.used(user_id, day, name)
            limit = self.limit_of(name, view)
            if limit is not None and used >= limit:
                raise QuotaExceededError(
                    params={
                        "kind": name,
                        "limit": limit,
                        "resets_at": self._midnight().isoformat(),
                    }
                )
        limit = (await self.limits.current()).nb_concurrent_artifacts
        await self.store.add_running(user_id, artifact_id)
        if len(await self.store.running(user_id)) > limit:
            await self.store.remove_running(user_id, artifact_id)
            raise BusyError(params={"what": "artifacts", "limit": limit})
        for name in self.counters_for(kind):
            await self.store.add(user_id, day, name)

    async def release(self, user_id: UUID, kind: ArtifactKind) -> None:
        """Take the daily count back (provider failures are not counted)."""
        day = local_today(self.clock)
        for name in self.counters_for(kind):
            await self.store.remove(user_id, day, name)

    async def finished(self, user_id: UUID, artifact_id: UUID) -> None:
        """The output is no longer running (ready, failed or canceled)."""
        await self.store.remove_running(user_id, artifact_id)

    async def started(self, user_id: UUID, artifact_id: UUID) -> None:
        """Re-mark an output as running (a retry or a re-kicked job)."""
        await self.store.add_running(user_id, artifact_id)

    async def running_count(self, user_id: UUID) -> int:
        """How many outputs are queued or generating now."""
        return len(await self.store.running(user_id))

    async def clear_running(self, user_id: UUID) -> None:
        """Forget every running output of the user (the account is deleted)."""
        await self.store.clear(user_id)
