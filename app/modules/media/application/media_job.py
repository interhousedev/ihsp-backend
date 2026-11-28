"""Use cases of the media job: enqueue, run, read."""

from uuid import UUID

from app.modules.media.domain.media_job import MediaJob, MediaKind, MediaStatus
from app.modules.media.domain.narration import (
    NarrationOptions,
    Segment,
    align_segments,
    build_vtt,
    timecode,
    validate_script,
)
from app.modules.media.ports.media import (
    MediaFiles,
    MediaJobStore,
    MediaKicker,
    MediaLimits,
    OwnerAccess,
    StaleMediaJobError,
    VideoRenderer,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    RateLimitedError,
    ValidationFailedError,
)
from app.shared.clock import Clock
from app.shared.contracts.material_sink import Material, MaterialSink
from app.shared.contracts.speech import SpeechSynthesizer
from app.shared.contracts.teaching_scope import TeachingScope

import structlog

log = structlog.get_logger()

MAX_CHARS = 20_000
MAX_LENGTH_S = 180
CHARS_PER_SECOND = 15.0
QUEUE = "media_render"
RUN_TASK = "media.run_job"


class MediaLimitError(RateLimitedError):
    """The weekly allowance of media jobs is used."""

    code = "media/limit"
    message_key = "media-limit"


def estimate_length_s(script: tuple[Segment, ...], speed: float) -> float:
    """Rough spoken length of the script."""
    return sum(len(s.text) for s in script) / CHARS_PER_SECOND / max(speed, 0.1)


class EnqueueMediaJob:
    """Validates and queues a media job (or reuses a delivered one)."""

    def __init__(
        self,
        store: MediaJobStore,
        kicker: MediaKicker,
        clock: Clock,
        limits: MediaLimits,
        scope: TeachingScope,
    ) -> None:
        """Bind the ports."""
        self.store = store
        self.kicker = kicker
        self.clock = clock
        self.limits = limits
        self.scope = scope

    async def execute(
        self,
        actor: Actor,
        kind: MediaKind,
        script: tuple[Segment, ...],
        options: NarrationOptions,
        *,
        subject_id: UUID,
        group_id: UUID | None = None,
    ) -> MediaJob:
        """Queue the job and start the worker."""
        if not (actor.has(Role.TEACHER) or actor.has(Role.ADMIN)):
            raise ForbiddenError(params={"roles": ["teacher", "admin"]})
        validate_script(script, language=options.language, max_chars=MAX_CHARS)
        if not await self.scope.can_teach(actor, subject_id, group_id):
            raise ForbiddenError(params={"subject": str(subject_id)})
        if estimate_length_s(script, options.speed) > MAX_LENGTH_S:
            raise ValidationFailedError(params={"max_seconds": MAX_LENGTH_S})
        job = MediaJob.queue(
            actor.user_id,
            kind,
            script,
            options,
            self.clock.now(),
            subject_id=subject_id,
            group_id=group_id,
        )
        for done in await self.store.find_done(actor.user_id, job.script_hash):
            if (done.subject_id, done.group_id) != (subject_id, group_id):
                continue
            if not done.delivered:
                await self.kicker.kick(RUN_TASK, str(done.id), queue=QUEUE)
            return done
        if await self.limits.used_this_week(actor.user_id) >= (
            self.limits.media_jobs_per_week
        ):
            raise MediaLimitError(params={"limit": self.limits.media_jobs_per_week})
        await self.store.add(job)
        await self.kicker.kick(RUN_TASK, str(job.id), queue=QUEUE)
        return job


def _failed(job: MediaJob) -> bool:
    """Whether the job is in the failed state."""
    return job.status is MediaStatus.FAILED


class RunMediaJob:
    """The worker: voice, render, store, deliver to the notebook."""

    def __init__(
        self,
        store: MediaJobStore,
        synthesizer: SpeechSynthesizer,
        renderer: VideoRenderer,
        files: MediaFiles,
        notebook_sink: MaterialSink,
        access: OwnerAccess,
    ) -> None:
        """Bind the ports."""
        self.store = store
        self.synthesizer = synthesizer
        self.renderer = renderer
        self.files = files
        self.sink = notebook_sink
        self.access = access

    async def execute(self, job_id: UUID) -> None:
        """Advance the job; safe to run again on redelivery."""
        job = await self.store.get(job_id)
        if job is None:
            return
        try:
            await self._advance(job)
        except StaleMediaJobError:
            log.info("media_job_lost_race", job_id=str(job_id))

    async def _advance(self, job: MediaJob) -> None:
        if job.status is MediaStatus.DONE:
            if not job.delivered:
                await self._deliver(job)
            return
        if job.status is MediaStatus.FAILED:
            return
        if not await self._ready(job):
            return
        await self._execute(job)

    async def _execute(self, job: MediaJob) -> None:
        """Run the job, reusing a finished identical one, then deliver it."""
        prior = await self._prior(job)
        job.start()
        await self.store.save(job)
        try:
            if prior is not None:
                self._reuse(job, prior)
            else:
                await self._produce(job)
        except _Cancelled:
            return
        except Exception as exc:  # noqa: BLE001 - any stage failure requeues the job
            log.warning("media_job_stage_failed", job_id=str(job.id), exc_info=True)
            job.fail(str(exc) or type(exc).__name__)
        await self.store.save(job)
        if job.status is MediaStatus.DONE:
            await self._deliver(job)

    async def _prior(self, job: MediaJob) -> MediaJob | None:
        """A finished job of the same owner with the same script, if any."""
        return next(
            (
                p
                for p in await self.store.find_done(job.owner_id, job.script_hash)
                if p.id != job.id and p.file_id is not None
            ),
            None,
        )

    async def _ready(self, job: MediaJob) -> bool:
        """Recover an interrupted job and check the owner may still run it."""
        if job.status in (MediaStatus.VOICING, MediaStatus.RENDERING):
            job.recover()
            await self.store.save(job)
            if _failed(job):
                return False
        if (
            await self.access.actor_for(job.owner_id, job.subject_id, job.group_id)
            is None
        ):
            job.cancel()
            await self.store.save(job)
            return False
        return True

    @staticmethod
    def _reuse(job: MediaJob, prior: MediaJob) -> None:
        assert prior.audio_file_id and prior.captions_file_id and prior.file_id
        job.voiced(
            prior.audio_file_id,
            prior.captions_file_id,
            prior.segments,
            prior.duration_ms,
        )
        if job.kind is MediaKind.VIDEO_WITH_VOICE:
            job.complete(prior.file_id, prior.storage_key or "")

    async def _produce(self, job: MediaJob) -> None:
        options = job.options
        audio, durations = bytearray(), []
        for segment in job.script:
            result = await self.synthesizer.synthesize(
                text=segment.text,
                language=options.language,
                voice_id=options.voice_id,
                speed=options.speed,
            )
            audio += result.audio
            durations.append(result.duration_ms)
        await self._ensure_running(job, MediaStatus.VOICING)
        segments = align_segments(job.script, durations)
        digest = job.script_hash
        audio_id = await self.files.put(
            owner_id=job.owner_id,
            name=f"{digest}.mp3",
            content=bytes(audio),
            mime="audio/mpeg",
        )
        captions_id = await self.files.put(
            owner_id=job.owner_id,
            name=f"{digest}.vtt",
            content=build_vtt(segments).encode(),
            mime="text/vtt",
        )
        total = sum(durations)
        job.voiced(audio_id, captions_id, segments, total)
        if job.kind is not MediaKind.VIDEO_WITH_VOICE:
            return
        await self.store.save(job)
        video = await self.renderer.render(
            composition_hash=digest,
            fmt="mp4",
            length_s=-(-total // 1000),
            segments=segments,
            audio=bytes(audio),
        )
        await self._ensure_running(job, MediaStatus.RENDERING)
        file_id = await self.files.put(
            owner_id=job.owner_id, name=f"{digest}.mp4", content=video, mime="video/mp4"
        )
        job.complete(file_id, MediaJob.storage_key_for(job.owner_id, digest, job.kind))

    async def _ensure_running(self, job: MediaJob, stage: MediaStatus) -> None:
        """Stop if somebody cancelled the job while a paid step ran."""
        fresh = await self.store.get(job.id)
        if fresh is None or fresh.status is not stage:
            raise _Cancelled
        if fresh is not job:
            job.version = fresh.version

    async def _deliver(self, job: MediaJob) -> None:
        actor = await self.access.actor_for(job.owner_id, job.subject_id, job.group_id)
        if actor is None or job.file_id is None:
            return
        title = job.script[0].text.strip()[:60] if job.script else "Media"
        body = (
            title
            + "\n\n"
            + "\n".join(f"[{timecode(s.start_ms)}] {s.text}" for s in job.segments)
        )
        try:
            await self.sink.store(
                actor,
                Material(
                    "media",
                    title,
                    body,
                    job.subject_id,
                    job.group_id,
                    job.segments,
                    job.file_id,
                ),
            )
        except Exception:  # noqa: BLE001 - the sweeper redelivers
            log.warning("media_delivery_failed", job_id=str(job.id), exc_info=True)
            return
        job.mark_delivered()
        await self.store.save(job)


class _Cancelled(Exception):
    """The job was cancelled while a stage ran."""


class GetMediaJob:
    """Owner (or admin) reads a job."""

    def __init__(self, store: MediaJobStore) -> None:
        """Bind the store."""
        self.store = store

    async def execute(self, actor: Actor, job_id: UUID) -> MediaJob:
        """The job; others get NotFound."""
        job = await self.store.get(job_id)
        if job is None or not (job.owner_id == actor.user_id or actor.has(Role.ADMIN)):
            raise NotFoundError(params={"id": str(job_id)})
        return job


class ListMediaJobs:
    """The caller's own jobs, newest first."""

    def __init__(self, store: MediaJobStore) -> None:
        """Bind the store."""
        self.store = store

    async def execute(
        self, actor: Actor, *, limit: int, offset: int
    ) -> tuple[list[MediaJob], int]:
        """One page and the total."""
        return await self.store.list_by_owner(actor.user_id, limit=limit, offset=offset)


class RetryMediaJob:
    """Owner (or admin) starts a failed job again."""

    def __init__(self, store: MediaJobStore, kicker: MediaKicker) -> None:
        """Bind the store and the kicker."""
        self.store = store
        self.kicker = kicker
        self._get = GetMediaJob(store)

    async def execute(self, actor: Actor, job_id: UUID) -> MediaJob:
        """Requeue a failed job; any other status is a conflict."""
        job = await self._get.execute(actor, job_id)
        if job.status is not MediaStatus.FAILED:
            raise ConflictError(params={"id": str(job_id), "status": job.status.value})
        job.retry()
        await self.store.save(job)
        await self.kicker.kick(RUN_TASK, str(job.id), queue=QUEUE)
        return job


class CancelMediaJob:
    """Owner (or admin) stops a job that has not finished."""

    def __init__(self, store: MediaJobStore) -> None:
        """Bind the store."""
        self.store = store
        self._get = GetMediaJob(store)

    async def execute(self, actor: Actor, job_id: UUID) -> MediaJob:
        """Cancel; a cancelled job stays cancelled, a finished one is a conflict."""
        job = await self._get.execute(actor, job_id)
        if job.status is MediaStatus.FAILED:
            return job
        if job.status is MediaStatus.DONE:
            raise ConflictError(params={"id": str(job_id), "status": "done"})
        job.cancel()
        await self.store.save(job)
        return job
