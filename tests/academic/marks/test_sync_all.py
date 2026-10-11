"""A whole EMIS sync run: selection, stats, the failure alert and the run lock."""

import asyncio
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.sync_all import SyncAll
from app.modules.academic.domain.marks.errors import SyncAlreadyRunningError
from app.shared.actor import Role
from app.shared.contracts.emis import EmisAuthFailed, EmisProfile
from app.shared.notifications import NotificationType
from tests.academic.marks.conftest import Env
from tests.academic.marks.db import runs
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.world import DAY, MATH_EMIS, add_student
from tests.fakes.key_lock import InMemoryKeyLock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

Maker = async_sessionmaker[AsyncSession]


async def _crowd(env: Env, maker: Maker, extra: int) -> list[UUID]:
    """Add active, backfilled students; return every student id, seeded one first."""
    ids = [env.world.user_id]
    for _ in range(extra):
        uid = await add_student(maker, env.world)
        env.identity.add(make_user(uid))
        ids.append(uid)
    return ids


async def test_run_stats_and_alert_when_more_than_a_fifth_fail(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-11: 3 of 10 fail: stats are stored and admins get `sync_alert`."""
    ids = await _crowd(env, sessionmaker_in_tx, 9)
    admin = env.identity.add(make_user(UUID(int=500), roles=frozenset({Role.ADMIN})))
    env.emis.unavailable_for = set(ids[:3])
    env.emis.set(make_ratings(MATH_EMIS, 3, [("lesson", DAY, 5)]))

    run_id = await env.sync_all().execute("11:30")

    [run] = await runs(sessionmaker_in_tx)
    assert run.id == run_id
    assert run.status == "done"
    assert run.finished_at == env.clock.now()
    assert run.stats == {
        "students_total": 10,
        "ok": 7,
        "failed": 3,
        "reauth": 0,
        "emis_requests": 17,  # 7 students x 2 subjects + 3 failed first requests
        "marks_new": 7,
    }
    alerts = [
        d for d in env.outbox.notifications if d.type == NotificationType.SYNC_ALERT
    ]
    assert [(a.user_id, a.payload, a.dedupe_key) for a in alerts] == [
        (
            admin.id,
            {"run_id": str(run_id), "failed": 3, "total": 10},
            f"sync-alert:{run_id}:{admin.id}",
        )
    ]
    marks = [d for d in env.outbox.notifications if d.type == NotificationType.MARKS]
    assert len(marks) == 7


async def test_no_alert_at_ten_percent_failures(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """1 of 10 failing is below the alert level."""
    ids = await _crowd(env, sessionmaker_in_tx, 9)
    env.identity.add(make_user(UUID(int=500), roles=frozenset({Role.ADMIN})))
    env.emis.unavailable_for = {ids[0]}

    await env.sync_all().execute("15:00")

    assert not [
        d for d in env.outbox.notifications if d.type == NotificationType.SYNC_ALERT
    ]
    [run] = await runs(sessionmaker_in_tx)
    assert (run.stats["ok"], run.stats["failed"]) == (9, 1)


async def test_reauth_is_counted_separately_and_does_not_alert(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """Rejected credentials are `reauth`, not `failed`."""
    env.identity.add(make_user(UUID(int=500), roles=frozenset({Role.ADMIN})))
    env.emis.error = EmisAuthFailed()

    await env.sync_all().execute("11:30")

    [run] = await runs(sessionmaker_in_tx)
    assert (run.stats["reauth"], run.stats["failed"], run.stats["ok"]) == (1, 0, 0)
    assert [d.type for d in env.outbox.notifications] == [NotificationType.EMIS_REAUTH]


async def test_only_working_backfilled_students_are_selected(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """Students without a finished backfill or with a broken link are left out."""
    pending = await add_student(sessionmaker_in_tx, env.world, backfilled=False)
    env.identity.add(make_user(pending))
    broken = await add_student(sessionmaker_in_tx, env.world)
    env.identity.add(make_user(broken, emis_status="needs_reauth"))

    await env.sync_all().execute("11:30")

    [run] = await runs(sessionmaker_in_tx)
    assert run.stats["students_total"] == 1


async def test_the_evening_run_refreshes_profiles(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """Only the 20:00 slot runs in profile mode (SYNC-3)."""
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("11:30")
    assert "profile" not in {name for name, _s, _m in env.emis.calls}
    await env.sync_all().execute("20:00")
    assert "profile" in {name for name, _s, _m in env.emis.calls}
    assert len(await runs(sessionmaker_in_tx)) == 2


async def test_students_are_spread_over_twenty_minutes(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """Student i starts after i * 1200 / n seconds."""
    await _crowd(env, sessionmaker_in_tx, 3)
    delays: list[float] = []

    async def record(seconds: float) -> None:
        delays.append(seconds)

    sync_all = SyncAll(
        uow_factory=env.uow_factory,
        sync_student=env.sync,
        bell_sync=env.bells,
        timetable_sync=env.timetables,
        identity=env.identity,  # type: ignore[arg-type]
        clock=env.clock,
        concurrency=1,
        sleep=record,
    )
    await sync_all.execute("manual")

    assert sorted(delays) == [0.0, 300.0, 600.0, 900.0]


async def test_the_evening_run_syncs_the_bells_once_for_everyone(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ACA-4: class hours are the same for all students: one call per run."""
    ids = await _crowd(env, sessionmaker_in_tx, 2)
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("20:00")

    assert len(env.bells.calls) == 1 and env.bells.calls[0] in ids


async def test_the_other_runs_leave_the_bells_alone(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ACA-4: only the 20:00 profile run refreshes the bells."""
    await _crowd(env, sessionmaker_in_tx, 1)

    for slot in ("11:30", "15:00", "manual"):
        await env.sync_all().execute(slot)

    assert env.bells.calls == []


async def test_a_failed_bell_sync_tries_the_next_student_and_never_fails_the_run(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ID-7: one student's broken EMIS link must not decide the lyceum's bells."""
    ids = await _crowd(env, sessionmaker_in_tx, 3)
    env.bells.fail_for = set(ids[:2])
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("20:00")

    assert env.bells.calls[-1] not in env.bells.fail_for or len(env.bells.calls) == 3
    [run] = await runs(sessionmaker_in_tx)
    assert run.status == "done"


async def test_when_no_link_works_the_run_still_finishes(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ID-7: bells are retried the next evening."""
    ids = await _crowd(env, sessionmaker_in_tx, 1)
    env.bells.fail_for = set(ids)
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("20:00")

    assert len(env.bells.calls) == 2
    [run] = await runs(sessionmaker_in_tx)
    assert run.status == "done"


async def test_the_evening_run_refreshes_each_group_once_per_half(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ACA-1: a student sees only their own half, so one student per half is asked."""
    ids = await _crowd(env, sessionmaker_in_tx, 3)
    await _set_subgroups(
        sessionmaker_in_tx, {ids[0]: 1, ids[1]: 1, ids[2]: 2, ids[3]: None}
    )
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("20:00")

    asked = {user_id for _, user_id, _ in env.timetables.calls}
    assert len(env.timetables.calls) == 3
    assert asked == {ids[0], ids[2], ids[3]}  # first of half 1, of half 2, of unknown
    assert {group for group, _, _ in env.timetables.calls} == {env.world.group_id}
    assert all(refresh is False for _, _, refresh in env.timetables.calls)


async def test_the_other_runs_leave_the_timetables_alone(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ACA-1: only the 20:00 profile run reads timetables."""
    await _crowd(env, sessionmaker_in_tx, 1)

    for slot in ("11:30", "15:00", "manual"):
        await env.sync_all().execute(slot)

    assert env.timetables.calls == []


async def test_a_broken_link_makes_the_next_student_of_that_half_try(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """ID-7: one student's EMIS password must not stop their group's timetable."""
    ids = await _crowd(env, sessionmaker_in_tx, 3)
    env.timetables.fail_for = {ids[0]}
    env.timetables.raise_for = {ids[1]}
    env.emis.profile_result = EmisProfile(1, "A", "B", None, 10815, 3292, "2TN2", 3, 1)

    await env.sync_all().execute("20:00")

    assert [user_id for _, user_id, _ in env.timetables.calls] == ids[:3]
    [run] = await runs(sessionmaker_in_tx)
    assert run.status == "done"


async def _set_subgroups(maker: Maker, subgroups: dict[UUID, int | None]) -> None:
    from app.modules.academic.infrastructure.orm.student import Student

    import sqlalchemy as sa

    async with maker() as session:
        for user_id, subgroup in subgroups.items():
            await session.execute(
                sa.update(Student)
                .where(Student.user_id == user_id)
                .values(subgroup=subgroup)
            )
        await session.commit()


def _sync_all(env: Env, lock: InMemoryKeyLock, **overrides: Any) -> SyncAll:
    """SyncAll with the lock and any collaborator replaced."""
    parts: dict[str, Any] = {
        "uow_factory": env.uow_factory,
        "sync_student": env.sync,
        "bell_sync": env.bells,
        "timetable_sync": env.timetables,
        "identity": env.identity,
        "clock": env.clock,
        "concurrency": 1,
        "spread_seconds": 0,
        "lock": lock,
    }
    parts.update(overrides)
    return SyncAll(**parts)


async def test_a_second_run_during_the_first_is_refused(
    env: Env, sessionmaker_in_tx: Maker
) -> None:
    """SYNC-1: the `academic:sync_all` lock keeps an overlapping run out."""
    lock = InMemoryKeyLock()
    started = asyncio.Event()
    release = asyncio.Event()

    async def slow(user_id: UUID, run_id: UUID, **kwargs: Any) -> Any:
        started.set()
        await release.wait()
        return await env.sync.execute(user_id, run_id, **kwargs)

    first = _sync_all(env, lock, sync_student=SimpleNamespace(execute=slow))
    task = asyncio.create_task(first.execute("11:30"))
    await started.wait()

    with pytest.raises(SyncAlreadyRunningError):
        await _sync_all(env, lock).execute("15:00")

    release.set()
    await task
    assert lock.held == {}
    assert len(await runs(sessionmaker_in_tx)) == 1


async def test_the_lock_is_freed_when_the_run_fails(env: Env) -> None:
    """A crashed run must not block the next slot until the TTL."""
    lock = InMemoryKeyLock()

    async def boom(*args: Any, **kwargs: Any) -> Any:
        raise RuntimeError("identity is down")

    broken = _sync_all(env, lock, identity=SimpleNamespace(get_users=boom))

    with pytest.raises(RuntimeError):
        await broken.execute("11:30")

    assert lock.held == {}
    assert await _sync_all(env, lock).execute("11:30")
