"""Long worker jobs that admins can see and stop (EMIS pulls, material re-syncs).

A job is registered ``queued`` when an admin kicks it (``JobTracker.enqueue``) or
straight ``running`` when the worker starts one on its own (``run_job``). While
it runs, the code deep inside reaches it through a context variable, so use cases
need no extra parameters:

    async with run_job(tracker, "emis.resync_materials", "Materials 2026/1") as job:
        for group in groups:
            if await job_should_stop():   # cooperative cancellation
                raise JobCancelled()
            ...
            await job_progress(done=i, total=len(groups))

``tracker.cancel(id)`` sets a cancel flag: a queued job is dropped at once (the
worker skips it when the message arrives), a running one stops at its next check.
"""

import datetime as dt
import json
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass, field, replace
from typing import Literal, Protocol
from uuid import uuid4

from app.shared.base_error import NotFoundError

from redis.asyncio import Redis

JobStatus = Literal["queued", "running", "stopping", "done", "failed", "cancelled"]
ACTIVE: frozenset[str] = frozenset({"queued", "running", "stopping"})
JOB_TTL_SECONDS = 24 * 3600
STOP_CHECK_SECONDS = 1.0  # should_stop asks Redis at most once a second


class JobCancelledError(Exception):
    """Raised inside a job when an admin asked it to stop."""


JobCancelled = JobCancelledError  # the short name other modules import


@dataclass(slots=True)
class JobInfo:
    """What the admin list shows of one job."""

    id: str
    kind: str
    label: str
    status: JobStatus
    created_at: str
    started_at: str | None = None
    finished_at: str | None = None
    started_by: str | None = None
    done: int = 0
    total: int | None = None
    note: str | None = None
    counters: dict[str, int] = field(default_factory=dict)


def _now() -> str:
    return dt.datetime.now(dt.UTC).isoformat()


class JobTracker(Protocol):
    """Where jobs live (Redis in the processes, memory in tests)."""

    async def save(self, job: JobInfo) -> None:
        """Store the job (replacing it)."""
        ...

    async def get(self, job_id: str) -> JobInfo | None:
        """Return the job, or None when unknown or expired."""
        ...

    async def list_all(self) -> list[JobInfo]:
        """Every known job, newest first."""
        ...

    async def flag_cancel(self, job_id: str) -> None:
        """Raise the cancel flag of the job."""
        ...

    async def is_cancelled(self, job_id: str) -> bool:
        """Say whether the cancel flag is raised."""
        ...


class MemoryJobTracker:
    """JobTracker in memory (tests, fake wiring)."""

    def __init__(self) -> None:
        """Start empty."""
        self.jobs: dict[str, JobInfo] = {}
        self.flags: set[str] = set()

    async def save(self, job: JobInfo) -> None:
        """Store the job."""
        self.jobs[job.id] = replace(job, counters=dict(job.counters))

    async def get(self, job_id: str) -> JobInfo | None:
        """Return the job."""
        return self.jobs.get(job_id)

    async def list_all(self) -> list[JobInfo]:
        """Every job, newest first."""
        return sorted(self.jobs.values(), key=lambda j: j.created_at, reverse=True)

    async def flag_cancel(self, job_id: str) -> None:
        """Raise the cancel flag."""
        self.flags.add(job_id)

    async def is_cancelled(self, job_id: str) -> bool:
        """Say whether the flag is raised."""
        return job_id in self.flags


class RedisJobTracker:
    """``jobs:{id}`` holds the job, ``jobs:{id}:cancel`` the flag, ``jobs:index``."""

    INDEX = "jobs:index"

    def __init__(self, redis: Redis) -> None:
        """Store the client (``decode_responses=True``)."""
        self.redis = redis

    async def save(self, job: JobInfo) -> None:
        """Store the job for a day and index it by creation time."""
        await self.redis.set(
            f"jobs:{job.id}", json.dumps(asdict(job)), ex=JOB_TTL_SECONDS
        )
        score = dt.datetime.fromisoformat(job.created_at).timestamp()
        await self.redis.zadd(self.INDEX, {job.id: score})

    async def get(self, job_id: str) -> JobInfo | None:
        """Return the job."""
        raw = await self.redis.get(f"jobs:{job_id}")
        return JobInfo(**json.loads(raw)) if raw else None

    async def list_all(self) -> list[JobInfo]:
        """Every job still stored, newest first; expired ids leave the index."""
        await self.redis.zremrangebyscore(
            self.INDEX, "-inf", time.time() - JOB_TTL_SECONDS
        )
        ids = await self.redis.zrevrange(self.INDEX, 0, 199)
        jobs = []
        for job_id in ids:
            job = await self.get(job_id)
            if job is not None:
                jobs.append(job)
        return jobs

    async def flag_cancel(self, job_id: str) -> None:
        """Raise the flag for a day."""
        await self.redis.set(f"jobs:{job_id}:cancel", "1", ex=JOB_TTL_SECONDS)

    async def is_cancelled(self, job_id: str) -> bool:
        """Say whether the flag is raised."""
        return bool(await self.redis.exists(f"jobs:{job_id}:cancel"))


async def enqueue(
    tracker: JobTracker, kind: str, label: str, *, started_by: str | None = None
) -> str:
    """Register a queued job; pass the returned id to the task as ``job_id``."""
    job = JobInfo(
        id=uuid4().hex,
        kind=kind,
        label=label,
        status="queued",
        created_at=_now(),
        started_by=started_by,
    )
    await tracker.save(job)
    return job.id


async def cancel(tracker: JobTracker, job_id: str) -> JobInfo | None:
    """Ask the job to stop; a queued one is cancelled at once. None: unknown."""
    job = await tracker.get(job_id)
    if job is None:
        return None
    if job.status not in ACTIVE:
        return job
    await tracker.flag_cancel(job_id)
    job.status = "cancelled" if job.status == "queued" else "stopping"
    if job.status == "cancelled":
        job.finished_at = _now()
    await tracker.save(job)
    return job


class JobHandle:
    """The running job: progress reports and the cancel check."""

    def __init__(self, tracker: JobTracker, job: JobInfo) -> None:
        """Wrap the stored job."""
        self.tracker = tracker
        self.job = job
        self._checked = 0.0
        self._stop = False

    async def progress(
        self,
        *,
        done: int | None = None,
        total: int | None = None,
        note: str | None = None,
        add: dict[str, int] | None = None,
    ) -> None:
        """Update the counters shown to admins (``add`` increments named ones)."""
        if done is not None:
            self.job.done = done
        if total is not None:
            self.job.total = total
        if note is not None:
            self.job.note = note
        for name, value in (add or {}).items():
            self.job.counters[name] = self.job.counters.get(name, 0) + value
        await self._save()

    async def should_stop(self) -> bool:
        """True once an admin asked to stop (checked at most once a second)."""
        if self._stop:
            return True
        now = time.monotonic()
        if now - self._checked >= STOP_CHECK_SECONDS:
            self._checked = now
            self._stop = await self.tracker.is_cancelled(self.job.id)
        return self._stop

    async def _save(self) -> None:
        stored = await self.tracker.get(self.job.id)
        if stored is not None and stored.status == "stopping":
            self.job.status = "stopping"  # keep the admin's request visible
        await self.tracker.save(self.job)


current_job: ContextVar[JobHandle | None] = ContextVar("current_job", default=None)


async def job_should_stop() -> bool:
    """True when the current job (if any) was asked to stop."""
    handle = current_job.get()
    return handle is not None and await handle.should_stop()


async def job_progress(
    *,
    done: int | None = None,
    total: int | None = None,
    note: str | None = None,
    add: dict[str, int] | None = None,
) -> None:
    """Report progress of the current job; nothing outside a job."""
    handle = current_job.get()
    if handle is not None:
        await handle.progress(done=done, total=total, note=note, add=add)


@asynccontextmanager
async def run_job(
    tracker: JobTracker,
    kind: str,
    label: str,
    *,
    job_id: str | None = None,
    started_by: str | None = None,
) -> AsyncIterator[JobHandle | None]:
    """Run a block as a visible job; yields None when it was cancelled while queued.

    JobCancelled raised inside ends the job as ``cancelled`` (not re-raised); any
    other error marks it ``failed`` and propagates.
    """
    job = await tracker.get(job_id) if job_id else None
    if job is None:
        job = JobInfo(
            id=job_id or uuid4().hex,
            kind=kind,
            label=label,
            status="queued",
            created_at=_now(),
            started_by=started_by,
        )
    if job.status == "cancelled" or await tracker.is_cancelled(job.id):
        job.status = "cancelled"
        job.finished_at = job.finished_at or _now()
        await tracker.save(job)
        yield None
        return
    job.status = "running"
    job.started_at = _now()
    handle = JobHandle(tracker, job)
    await tracker.save(job)
    token = current_job.set(handle)
    try:
        yield handle
        job.status = "cancelled" if handle._stop else "done"
    except JobCancelledError:
        job.status = "cancelled"
    except BaseException:
        job.status = "failed"
        raise
    finally:
        current_job.reset(token)
        job.finished_at = _now()
        await tracker.save(job)


class JobNotFoundError(NotFoundError):
    """No such job (unknown, or finished more than a day ago)."""

    code = "admin/job-not-found"
