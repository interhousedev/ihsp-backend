"""A whole EMIS sync run: selection, stats and the failure alert."""

from uuid import UUID

from app.modules.academic.application.marks.sync_all import SyncAll
from app.shared.actor import Role
from app.shared.contracts.emis import EmisAuthFailed, EmisProfile
from app.shared.notifications import NotificationType
from tests.academic.marks.conftest import Env
from tests.academic.marks.db import runs
from tests.academic.marks.fakes.emis import make_ratings
from tests.academic.marks.fakes.identity import make_user
from tests.academic.marks.world import DAY, MATH_EMIS, add_student

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
        identity=env.identity,  # type: ignore[arg-type]
        clock=env.clock,
        concurrency=1,
        sleep=record,
    )
    await sync_all.execute("manual")

    assert sorted(delays) == [0.0, 300.0, 600.0, 900.0]
