"""Sync with proof: two registrations at once, one sync fails, the retry repairs it."""

import asyncio
from uuid import UUID

from app.modules.academic.application.marks.sync_student import SyncOutcome
from app.modules.academic.application.schedule.run_student_sync import (
    RetryStudentSyncs,
    RunStudentSync,
)
from app.modules.academic.application.schedule.student_sync_jobs import MAX_ATTEMPTS
from app.modules.academic.domain.marks.sync import SyncCounters
from app.shared.actor import Role
from app.shared.contracts.emis import EmisUnavailable
from tests.academic.schedule.curriculum_builders import make_curriculum
from tests.academic.schedule.emis_builders import weekly
from tests.academic.schedule.env import Env
from tests.factories import make_actor as build_actor
from tests.fakes.academic.schedule.identity import make_user


class FakeBackfill:
    """Stands in for the marks step: three marks per successful run."""

    def __init__(self) -> None:
        self.calls: list[UUID] = []

    async def execute(
        self, user_id: UUID, counters: SyncCounters | None = None
    ) -> SyncOutcome:
        """Record the call and count the marks."""
        self.calls.append(user_id)
        if counters is not None:
            counters.marks_new += 3
        return SyncOutcome(user_id, "ok")


def _runner(env: Env, backfill: FakeBackfill) -> RunStudentSync:
    return RunStudentSync(
        jobs=env.emis_import.sync_jobs,
        sync_all=env.emis_import.sync_student_all,
        backfill=backfill,  # type: ignore[arg-type]
        uow_factory=env.uow_factory,
        clock=env.clock,
        identity=env.identity,  # type: ignore[arg-type]
    )


async def test_two_registrations_one_sync_fails_then_the_retry_repairs_it(
    env: Env,
) -> None:
    """Both students get a durable job; B's EMIS fails once; the retry then succeeds."""
    group = await env.group("2TN2", emis_group_id=3292)
    a = await env.student(group, subgroup=2)
    b = await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    env.emis.classes = weekly(2, 0) + weekly(3, 1)
    jobs = env.emis_import.sync_jobs
    await env.services.enrollment.enqueue_student_sync(a.id)
    await env.services.enrollment.enqueue_student_sync(b.id)

    original = env.emis.timetable
    down = {b.id}

    async def flaky(user_id: UUID, begin: object, end: object) -> object:
        if user_id in down:
            raise EmisUnavailable(support_details="EMIS down")
        return await original(user_id, begin, end)  # type: ignore[arg-type]

    env.emis.timetable = flaky  # type: ignore[method-assign]
    backfill = FakeBackfill()
    runner = _runner(env, backfill)

    if env.kind == "fake":  # both runs overlap; the SQL harness shares one connection
        first_a, first_b = await asyncio.gather(
            runner.execute(a.id), runner.execute(b.id)
        )
    else:
        first_a = await runner.execute(a.id)
        first_b = await runner.execute(b.id)

    assert first_a is not None and first_a.status == "succeeded"
    assert (first_a.subgroup, first_a.marks_count, first_a.attempts) == (2, 3, 1)
    assert first_b is not None and first_b.status == "failed"
    assert first_b.attempts == 1
    assert first_b.last_error is not None
    assert first_b.next_attempt_at is not None
    assert first_b.next_attempt_at > env.clock.now()

    # Not due yet: the retry job kicks nobody.
    assert (
        await RetryStudentSyncs(jobs=jobs, kicker=env.kicker, clock=env.clock).execute()
        == 0
    )

    # Later, EMIS answers again: the retry job kicks B and the run repairs it.
    down.clear()
    env.clock.advance(minutes=5)
    assert (
        await RetryStudentSyncs(jobs=jobs, kicker=env.kicker, clock=env.clock).execute()
        == 1
    )
    assert env.kicker.calls[-1] == (
        "academic.run_student_sync",
        {"user_id": str(b.id)},
    )
    repaired = await runner.execute(b.id)

    assert repaired is not None
    assert (repaired.status, repaired.attempts) == ("succeeded", 2)
    assert (repaired.subgroup, repaired.marks_count) == (None, 3)
    assert repaired.last_error is None
    # A succeeded job is never run again, by a kick or by the retry job.
    await runner.execute(a.id)
    assert backfill.calls.count(a.id) == 1
    assert (
        await RetryStudentSyncs(jobs=jobs, kicker=env.kicker, clock=env.clock).execute()
        == 0
    )


async def test_a_failing_student_gives_up_after_max_attempts_and_alerts(
    env: Env,
) -> None:
    """After MAX_ATTEMPTS the job stops retrying and an audit event says so."""
    group = await env.group("2TN2", emis_group_id=3292)
    b = await env.student(group)
    env.emis.curriculum_result = make_curriculum()
    env.emis.timetable_error = EmisUnavailable(support_details="EMIS down")
    admin = make_user(roles=frozenset({Role.ADMIN}))
    env.identity.add(admin)
    await env.services.enrollment.enqueue_student_sync(b.id)
    runner = _runner(env, FakeBackfill())

    for _ in range(MAX_ATTEMPTS):
        env.clock.advance(hours=2)
        await runner.execute(b.id)

    job = await env.emis_import.sync_jobs.get(b.id)
    assert job is not None
    assert (job.status, job.attempts) == ("failed", MAX_ATTEMPTS)
    env.clock.advance(days=1)
    assert await env.emis_import.sync_jobs.due(env.clock.now(), 10) == []
    if env.store is not None:  # the in-memory schedule keeps its audit drafts
        assert any(a.type == "student_sync.gave_up" for a in env.store.audits)
        assert any(n.type == "student_sync_failed" for n in env.store.notifications)


async def test_a_manual_request_resets_a_failed_job_once(env: Env) -> None:
    """The settings button queues a failed job; a second press changes nothing."""
    group = await env.group("2TN2", emis_group_id=3292)
    b = await env.student(group)
    actor = build_actor(Role.STUDENT, user_id=b.id)
    await env.services.enrollment.enqueue_student_sync(b.id)
    jobs = env.emis_import.sync_jobs
    await jobs.claim(b.id, env.clock.now())
    await jobs.fail(
        b.id,
        env.clock.now(),
        error="boom",
        next_attempt_at=env.clock.now(),
    )

    first = await env.emis_import.request_student_sync.execute(actor)
    second = await env.emis_import.request_student_sync.execute(actor)

    assert (first.status, first.attempts) == ("pending", 0)
    assert second == first
    assert env.kicker.names().count("academic.run_student_sync") == 1
