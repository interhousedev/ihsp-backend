"""Sync with proof: the durable record of a student's initial EMIS sync (port).

The row is written with the registration (same request, before the identity commit)
so a lost task kick cannot lose the work: the periodic retry job finds every row that
is pending or failed and due. One row per student; `claim` is the only way to start
an attempt, so a manual request, a kick and the retry job never run one student twice.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Literal, Protocol
from uuid import UUID

JobStatus = Literal["pending", "running", "succeeded", "failed"]
MAX_ATTEMPTS = 6
RUNNING_STALE_SECONDS = 30 * 60  # a worker that died mid-run releases its claim


@dataclass(frozen=True, slots=True)
class StudentSyncJob:
    """Where a student's initial sync is and what it has synced so far."""

    user_id: UUID
    status: JobStatus
    attempts: int
    requested_at: dt.datetime
    next_attempt_at: dt.datetime | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None
    last_error: str | None = None
    subgroup: int | None = None
    marks_count: int | None = None


def backoff_seconds(attempts: int) -> int:
    """Pause before the next attempt: 1, 2, 4 ... minutes, at most one hour."""
    return min(60 << max(attempts - 1, 0), 3600)


class StudentSyncJobs(Protocol):
    """Read and write the sync jobs; each call is one short transaction."""

    async def enqueue(self, user_id: UUID, now: dt.datetime) -> None:
        """Create or reset the job as pending, due now (registration)."""
        ...

    async def request(
        self, user_id: UUID, now: dt.datetime
    ) -> tuple[StudentSyncJob, bool]:
        """Manual request: queue a missing or failed job; return it and whether queued.

        A job that is pending, running or succeeded is returned unchanged.
        """
        ...

    async def get(self, user_id: UUID) -> StudentSyncJob | None:
        """Return the job, or None when the student has none."""
        ...

    async def claim(self, user_id: UUID, now: dt.datetime) -> StudentSyncJob | None:
        """Start an attempt if the job is due; None when it is not due or taken."""
        ...

    async def succeed(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        subgroup: int | None,
        marks_count: int,
    ) -> None:
        """Mark the attempt as succeeded and store what was synced."""
        ...

    async def fail(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        error: str,
        next_attempt_at: dt.datetime,
    ) -> None:
        """Mark the attempt as failed and set when the next one may run."""
        ...

    async def due(self, now: dt.datetime, limit: int) -> list[UUID]:
        """Students whose job can be claimed now (pending, failed or stale running)."""
        ...

    async def list_by_status(
        self, status: JobStatus, limit: int
    ) -> list[StudentSyncJob]:
        """Jobs in one status, most recently changed first (admin view)."""
        ...
