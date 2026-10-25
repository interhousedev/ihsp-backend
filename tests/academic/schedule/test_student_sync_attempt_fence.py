"""A late attempt must not overwrite the job state of a newer attempt."""

import datetime as dt
from uuid import uuid4

from app.modules.academic.infrastructure.schedule.student_sync_jobs import (
    MemoryStudentSyncJobs,
)

NOW = dt.datetime(2026, 10, 18, 9, 0, tzinfo=dt.UTC)


async def test_stale_attempt_cannot_overwrite_newer_success() -> None:
    jobs = MemoryStudentSyncJobs()
    user_id = uuid4()
    await jobs.enqueue(user_id, NOW)
    first = await jobs.claim(user_id, NOW)
    assert first is not None and first.attempts == 1

    # The first attempt is considered stale, a second one takes over and succeeds.
    later = NOW + dt.timedelta(hours=2)
    second = await jobs.claim(user_id, later)
    assert second is not None and second.attempts == 2
    await jobs.succeed(
        user_id, later, attempt=second.attempts, subgroup=3, marks_count=7
    )

    # The late first attempt now reports a failure and a success: both are ignored.
    await jobs.fail(
        user_id,
        later,
        attempt=first.attempts,
        error="late",
        next_attempt_at=later,
    )
    await jobs.succeed(
        user_id, later, attempt=first.attempts, subgroup=9, marks_count=0
    )

    job = await jobs.get(user_id)
    assert job is not None
    assert job.status == "succeeded"
    assert job.subgroup == 3
    assert job.marks_count == 7
    assert job.last_error is None


async def test_stale_attempt_cannot_overwrite_newer_running_job() -> None:
    jobs = MemoryStudentSyncJobs()
    user_id = uuid4()
    await jobs.enqueue(user_id, NOW)
    first = await jobs.claim(user_id, NOW)
    assert first is not None
    later = NOW + dt.timedelta(hours=2)
    second = await jobs.claim(user_id, later)
    assert second is not None

    await jobs.fail(
        user_id, later, attempt=first.attempts, error="late", next_attempt_at=later
    )

    job = await jobs.get(user_id)
    assert job is not None
    assert job.status == "running"
    assert job.attempts == second.attempts
