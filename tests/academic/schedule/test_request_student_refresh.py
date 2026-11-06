"""A1: a student's own EMIS refresh, at most once per cooldown."""

from typing import Any
from uuid import uuid4

from app.modules.academic.application.schedule.request_student_refresh import (
    RequestStudentRefresh,
    sync_error_code,
)
from app.modules.academic.infrastructure.schedule.student_sync_jobs import (
    MemoryStudentSyncJobs,
)
from app.modules.academic.infrastructure.schedule.sync_cooldown import (
    RedisSyncCooldown,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.fakes.clock import FixedClock

import pytest
from fakeredis.aioredis import FakeRedis


class Kicker:
    def __init__(self, *, fail: bool = False) -> None:
        self.kicks: list[dict[str, Any]] = []
        self.fail = fail

    async def kick(self, task_name: str, **kwargs: Any) -> None:
        if self.fail:
            raise RuntimeError("broker down")
        self.kicks.append({"task": task_name, **kwargs})


def _build(kicker: Kicker | None = None) -> tuple[Any, ...]:
    jobs = MemoryStudentSyncJobs()
    kicker = kicker or Kicker()
    clock = FixedClock()
    use_case = RequestStudentRefresh(
        jobs=jobs,
        kicker=kicker,
        clock=clock,
        cooldown=RedisSyncCooldown(FakeRedis(decode_responses=True)),
        cooldown_seconds=1800,
    )
    return use_case, jobs, kicker, clock


def _student() -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset({Role.STUDENT}))


async def test_first_refresh_queues_a_real_job() -> None:
    """A1: queued and kicked for the caller, even after an earlier success."""
    use_case, jobs, kicker, clock = _build()
    actor = _student()
    await jobs.enqueue(actor.user_id, clock.now())
    claimed = await jobs.claim(actor.user_id, clock.now())
    assert claimed is not None
    await jobs.succeed(
        actor.user_id, clock.now(), attempt=1, subgroup=None, marks_count=0
    )

    outcome = await use_case.execute(actor)

    assert outcome.status == "queued"
    assert outcome.job.status == "pending"
    assert [k["user_id"] for k in kicker.kicks] == [str(actor.user_id)]


async def test_a_second_call_returns_the_same_job_without_a_kick() -> None:
    """A1: pending job: same job, nothing more."""
    use_case, _, kicker, _ = _build()
    actor = _student()
    first = await use_case.execute(actor)
    second = await use_case.execute(actor)

    assert second.status == "running"
    assert second.job.requested_at == first.job.requested_at
    assert len(kicker.kicks) == 1


async def test_cooldown_refuses_until_it_expires() -> None:
    """A1: a finished job within the cooldown gives retry_after_seconds."""
    use_case, jobs, kicker, clock = _build()
    actor = _student()
    await use_case.execute(actor)
    await jobs.claim(actor.user_id, clock.now())
    await jobs.succeed(
        actor.user_id, clock.now(), attempt=1, subgroup=None, marks_count=1
    )

    outcome = await use_case.execute(actor)

    assert outcome.status == "cooldown"
    assert 0 < outcome.retry_after_seconds <= 1800
    assert len(kicker.kicks) == 1


async def test_one_students_cooldown_does_not_touch_another() -> None:
    """A1: the cooldown and the job are per student."""
    use_case, _, kicker, _ = _build()
    await use_case.execute(_student())
    other = await use_case.execute(_student())
    assert other.status == "queued"
    assert len(kicker.kicks) == 2


async def test_a_lost_kick_keeps_the_durable_job() -> None:
    """A1: the periodic retry runs a job whose kick was lost."""
    use_case, _, _, _ = _build(Kicker(fail=True))
    outcome = await use_case.execute(_student())
    assert outcome.status == "queued"


async def test_only_students_may_refresh() -> None:
    """A1: another role is refused."""
    use_case, _, kicker, _ = _build()
    teacher = Actor(user_id=uuid4(), roles=frozenset({Role.TEACHER}))
    with pytest.raises(ForbiddenError):
        await use_case.execute(teacher)
    assert kicker.kicks == []


@pytest.mark.parametrize(
    ("raw", "code"),
    [
        (None, None),
        ("emis/auth-failed: secret detail", "emis_reauth_required"),
        ("StudentSyncIncompleteError: timetable:emis_unavailable", "emis_unavailable"),
        ("emis/paused: wait", "emis_unavailable"),
        ("stopped: by an administrator", "stopped"),
        ("ValueError: internal path /srv/app", "sync_failed"),
    ],
)
def test_last_error_becomes_a_fixed_code(raw: str | None, code: str | None) -> None:
    """A1: raw text never reaches the client."""
    assert sync_error_code(raw) == code
