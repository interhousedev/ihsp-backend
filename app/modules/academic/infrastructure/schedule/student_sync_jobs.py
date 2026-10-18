"""Where the student sync jobs live: PostgreSQL, or memory for tests and fake wiring."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.schedule.student_sync_jobs import (
    MAX_ATTEMPTS,
    RUNNING_STALE_SECONDS,
    JobStatus,
    StudentSyncJob,
)

from sqlalchemy import text

# Opens a schedule unit of work; the SQL store runs on its session.
UowFactory = Callable[[], Any]


def _stale_before(now: dt.datetime) -> dt.datetime:
    return now - dt.timedelta(seconds=RUNNING_STALE_SECONDS)


def _claimable(job: StudentSyncJob, now: dt.datetime) -> bool:
    """The same rule as the SQL claim: due pending, due failed, or a stale run."""
    if job.status == "running":
        return job.started_at is not None and job.started_at <= _stale_before(now)
    if job.next_attempt_at is None or job.next_attempt_at > now:
        return False
    if job.status == "pending":
        return True
    return job.status == "failed" and job.attempts < MAX_ATTEMPTS


class MemoryStudentSyncJobs:
    """The same semantics in memory (unit tests, fake wiring)."""

    def __init__(self) -> None:
        """Start empty."""
        self._jobs: dict[UUID, StudentSyncJob] = {}

    async def enqueue(self, user_id: UUID, now: dt.datetime) -> None:
        """Create or reset the job as pending, due now."""
        self._jobs[user_id] = StudentSyncJob(
            user_id=user_id,
            status="pending",
            attempts=0,
            requested_at=now,
            next_attempt_at=now,
        )

    async def request(
        self, user_id: UUID, now: dt.datetime
    ) -> tuple[StudentSyncJob, bool]:
        """Queue a missing or failed job; others are returned unchanged."""
        job = self._jobs.get(user_id)
        if job is not None and job.status in ("pending", "running", "succeeded"):
            return job, False
        await self.enqueue(user_id, now)
        return self._jobs[user_id], True

    async def get(self, user_id: UUID) -> StudentSyncJob | None:
        """Return the job, or None."""
        return self._jobs.get(user_id)

    async def claim(self, user_id: UUID, now: dt.datetime) -> StudentSyncJob | None:
        """Start an attempt when due."""
        job = self._jobs.get(user_id)
        if job is None or not _claimable(job, now):
            return None
        job = StudentSyncJob(
            user_id=job.user_id,
            status="running",
            attempts=job.attempts + 1,
            requested_at=job.requested_at,
            next_attempt_at=job.next_attempt_at,
            started_at=now,
        )
        self._jobs[user_id] = job
        return job

    async def succeed(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        attempt: int,
        subgroup: int | None,
        marks_count: int,
    ) -> None:
        """Mark succeeded, unless a newer attempt has taken over the job."""
        job = self._jobs[user_id]
        if job.status != "running" or job.attempts != attempt:
            return
        self._jobs[user_id] = StudentSyncJob(
            user_id=user_id,
            status="succeeded",
            attempts=job.attempts,
            requested_at=job.requested_at,
            started_at=job.started_at,
            finished_at=now,
            subgroup=subgroup,
            marks_count=marks_count,
        )

    async def fail(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        attempt: int,
        error: str,
        next_attempt_at: dt.datetime | None,
    ) -> None:
        """Mark failed, unless a newer attempt has taken over the job."""
        job = self._jobs[user_id]
        if job.status != "running" or job.attempts != attempt:
            return
        self._jobs[user_id] = StudentSyncJob(
            user_id=user_id,
            status="failed",
            attempts=job.attempts,
            requested_at=job.requested_at,
            next_attempt_at=next_attempt_at,
            started_at=job.started_at,
            finished_at=now,
            last_error=error,
        )

    async def due(self, now: dt.datetime, limit: int) -> list[UUID]:
        """Claimable students, oldest due first."""
        due = [j for j in self._jobs.values() if _claimable(j, now)]
        due.sort(key=lambda j: j.next_attempt_at or j.requested_at)
        return [j.user_id for j in due[:limit]]

    async def list_by_status(
        self, status: JobStatus, limit: int
    ) -> list[StudentSyncJob]:
        """Jobs in one status, newest first."""
        found = [j for j in self._jobs.values() if j.status == status]
        found.sort(key=lambda j: j.finished_at or j.requested_at, reverse=True)
        return found[:limit]


_COLUMNS = (
    "user_id, status, attempts, requested_at, next_attempt_at, started_at, "
    "finished_at, last_error, subgroup, marks_count"
)


def _row_to_job(row: Any) -> StudentSyncJob:
    return StudentSyncJob(
        user_id=row["user_id"],
        status=row["status"],
        attempts=row["attempts"],
        requested_at=row["requested_at"],
        next_attempt_at=row["next_attempt_at"],
        started_at=row["started_at"],
        finished_at=row["finished_at"],
        last_error=row["last_error"],
        subgroup=row["subgroup"],
        marks_count=row["marks_count"],
    )


class SqlStudentSyncJobs:
    """The jobs in `academic.student_sync_jobs`; each call is one transaction."""

    def __init__(self, uow_factory: UowFactory) -> None:
        """Store the schedule unit-of-work factory (its session runs the SQL)."""
        self._uow_factory = uow_factory

    async def _rows(self, sql: str, params: dict[str, Any]) -> list[Any]:
        async with self._uow_factory() as uow:
            result = await uow.session.execute(text(sql), params)
            rows = result.mappings().all()
            await uow.commit()
        return list(rows)

    async def enqueue(self, user_id: UUID, now: dt.datetime) -> None:
        """Upsert the job as pending, due now."""
        await self._rows(
            """
            INSERT INTO academic.student_sync_jobs
                (user_id, status, attempts, requested_at, next_attempt_at, updated_at)
            VALUES (:u, 'pending', 0, :now, :now, :now)
            ON CONFLICT (user_id) DO UPDATE SET status = 'pending', attempts = 0,
                requested_at = :now, next_attempt_at = :now, last_error = NULL,
                updated_at = :now
            RETURNING user_id
            """,
            {"u": user_id, "now": now},
        )

    async def request(
        self, user_id: UUID, now: dt.datetime
    ) -> tuple[StudentSyncJob, bool]:
        """Reset a failed job, or create a missing one; others are left as they are."""
        reset = await self._rows(
            """
            UPDATE academic.student_sync_jobs
            SET status = 'pending', attempts = 0, requested_at = :now,
                next_attempt_at = :now, last_error = NULL, updated_at = :now
            WHERE user_id = :u AND status = 'failed'
            RETURNING user_id
            """,
            {"u": user_id, "now": now},
        )
        queued = bool(reset)
        if not reset:
            created = await self._rows(
                """
                INSERT INTO academic.student_sync_jobs
                    (user_id, status, attempts, requested_at, next_attempt_at,
                     updated_at)
                VALUES (:u, 'pending', 0, :now, :now, :now)
                ON CONFLICT (user_id) DO NOTHING
                RETURNING user_id
                """,
                {"u": user_id, "now": now},
            )
            queued = bool(created)
        job = await self.get(user_id)
        assert job is not None  # the row was just updated or inserted
        return job, queued

    async def get(self, user_id: UUID) -> StudentSyncJob | None:
        """Return the job, or None."""
        rows = await self._rows(
            f"SELECT {_COLUMNS} FROM academic.student_sync_jobs WHERE user_id = :u",
            {"u": user_id},
        )
        return _row_to_job(rows[0]) if rows else None

    async def claim(self, user_id: UUID, now: dt.datetime) -> StudentSyncJob | None:
        """Start an attempt; the UPDATE re-checks the rule under the row lock."""
        rows = await self._rows(
            f"""
            UPDATE academic.student_sync_jobs
            SET status = 'running', attempts = attempts + 1, started_at = :now,
                updated_at = :now
            WHERE user_id = :u AND (
                (status = 'pending' AND next_attempt_at <= :now)
                OR (status = 'failed' AND attempts < :max AND next_attempt_at <= :now)
                OR (status = 'running' AND started_at <= :stale)
            )
            RETURNING {_COLUMNS}
            """,
            {
                "u": user_id,
                "now": now,
                "max": MAX_ATTEMPTS,
                "stale": _stale_before(now),
            },
        )
        return _row_to_job(rows[0]) if rows else None

    async def succeed(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        attempt: int,
        subgroup: int | None,
        marks_count: int,
    ) -> None:
        """Mark succeeded and store what was synced (only this attempt's own row)."""
        await self._rows(
            """
            UPDATE academic.student_sync_jobs
            SET status = 'succeeded', finished_at = :now, next_attempt_at = NULL,
                last_error = NULL, subgroup = :sub, marks_count = :marks,
                updated_at = :now
            WHERE user_id = :u AND status = 'running' AND attempts = :attempt
            RETURNING user_id
            """,
            {
                "u": user_id,
                "now": now,
                "sub": subgroup,
                "marks": marks_count,
                "attempt": attempt,
            },
        )

    async def fail(
        self,
        user_id: UUID,
        now: dt.datetime,
        *,
        attempt: int,
        error: str,
        next_attempt_at: dt.datetime | None,
    ) -> None:
        """Mark failed with the reason, only for this attempt's own row."""
        await self._rows(
            """
            UPDATE academic.student_sync_jobs
            SET status = 'failed', finished_at = :now, last_error = :err,
                next_attempt_at = :next, updated_at = :now
            WHERE user_id = :u AND status = 'running' AND attempts = :attempt
            RETURNING user_id
            """,
            {
                "u": user_id,
                "now": now,
                "err": error[:500],
                "next": next_attempt_at,
                "attempt": attempt,
            },
        )

    async def due(self, now: dt.datetime, limit: int) -> list[UUID]:
        """Claimable students, oldest due first."""
        rows = await self._rows(
            """
            SELECT user_id FROM academic.student_sync_jobs
            WHERE next_attempt_at <= :now AND (
                status = 'pending'
                OR (status = 'failed' AND attempts < :max)
                OR (status = 'running' AND started_at <= :stale)
            )
            ORDER BY next_attempt_at
            LIMIT :n
            """,
            {"now": now, "max": MAX_ATTEMPTS, "stale": _stale_before(now), "n": limit},
        )
        return [row["user_id"] for row in rows]

    async def list_by_status(
        self, status: JobStatus, limit: int
    ) -> list[StudentSyncJob]:
        """Jobs in one status, most recently changed first."""
        rows = await self._rows(
            f"""
            SELECT {_COLUMNS} FROM academic.student_sync_jobs
            WHERE status = :s ORDER BY updated_at DESC LIMIT :n
            """,
            {"s": status, "n": limit},
        )
        return [_row_to_job(row) for row in rows]
