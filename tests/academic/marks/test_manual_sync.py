"""Manual sync controls and the run list (ADM-14)."""

import datetime as dt
from collections.abc import Callable
from uuid import UUID

from app.modules.academic.application.marks.list_sync_runs import ListSyncRuns
from app.modules.academic.application.marks.run_manual_sync import RunManualSync
from app.modules.academic.domain.marks.errors import (
    StudentNotFoundError,
    SyncAlreadyRunningError,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.academic.marks.conftest import Env
from tests.academic.marks.fakes.enrollment import FakeSchedule
from tests.fakes.tasks import FakeTaskKicker

import pytest

MakeActor = Callable[..., Actor]


def _manual(env: Env, kicker: FakeTaskKicker, known: set[UUID]) -> RunManualSync:
    return RunManualSync(
        uow_factory=env.uow_factory,
        schedule=FakeSchedule(known),  # type: ignore[arg-type]
        kicker=kicker,
        clock=env.clock,
    )


async def test_one_student_is_kicked_and_audited(
    env: Env, kicker: FakeTaskKicker, make_actor: MakeActor
) -> None:
    """A manual run for one student starts the student task and writes an audit."""
    admin = make_actor(Role.ADMIN)
    manual = _manual(env, kicker, {env.world.user_id})

    await manual.execute(admin, env.world.user_id)

    assert kicker.calls == [
        (
            "academic.sync_student",
            {"user_id": str(env.world.user_id), "mode": "profile"},
        )
    ]
    [audit] = env.outbox.audits
    assert (audit.type, audit.actor_id, audit.user_id) == (
        "sync.manual_run",
        admin.user_id,
        env.world.user_id,
    )


async def test_unknown_student_and_non_admin_are_refused(
    env: Env, kicker: FakeTaskKicker, make_actor: MakeActor
) -> None:
    """404 for an unknown student, 403 for a non-administrator."""
    manual = _manual(env, kicker, set())
    with pytest.raises(StudentNotFoundError):
        await manual.execute(make_actor(Role.ADMIN), UUID(int=3))
    with pytest.raises(ForbiddenError):
        await manual.execute(make_actor(Role.TEACHER), None)
    assert kicker.calls == []


async def test_full_run_is_kicked_unless_one_is_running(
    env: Env, kicker: FakeTaskKicker, make_actor: MakeActor
) -> None:
    """A full run starts `academic.sync_all`; a fresh running run blocks another."""
    manual = _manual(env, kicker, set())
    admin = make_actor(Role.ADMIN)
    await manual.execute(admin, None)
    assert kicker.calls == [("academic.sync_all", {"slot": "manual"})]

    async with env.uow_factory() as uow:
        await uow.sync_runs.create(env.clock.now() - dt.timedelta(minutes=30))
        await uow.commit()
    with pytest.raises(SyncAlreadyRunningError):
        await manual.execute(admin, None)


async def test_a_stale_running_run_does_not_block(
    env: Env, kicker: FakeTaskKicker, make_actor: MakeActor
) -> None:
    """A run still marked running after three hours is considered dead."""
    async with env.uow_factory() as uow:
        await uow.sync_runs.create(env.clock.now() - dt.timedelta(hours=5))
        await uow.commit()

    await _manual(env, kicker, set()).execute(make_actor(Role.ADMIN), None)

    assert kicker.names() == ["academic.sync_all"]


async def test_runs_are_listed_newest_first_with_a_cursor(
    env: Env, make_actor: MakeActor
) -> None:
    """Pages of two: newest first, the cursor continues where the page ended."""
    created: list[UUID] = []
    for minutes in (0, 10, 20):
        async with env.uow_factory() as uow:
            run_id = await uow.sync_runs.create(
                env.clock.now() + dt.timedelta(minutes=minutes)
            )
            await uow.sync_runs.finish(
                run_id,
                finished_at=env.clock.now(),
                status="done",
                stats={"ok": minutes},
            )
            await uow.commit()
        created.append(run_id)
    admin = make_actor(Role.ADMIN)
    listing = ListSyncRuns(uow_factory=env.uow_factory)

    first = await listing.execute(admin, None, 2)
    assert [i["id"] for i in first.items] == [created[2], created[1]]
    assert first.next_cursor is not None
    second = await listing.execute(admin, first.next_cursor, 2)
    assert [i["id"] for i in second.items] == [created[0]]
    assert second.next_cursor is None
    assert second.items[0]["stats"] == {"ok": 0}
    with pytest.raises(ForbiddenError):
        await listing.execute(make_actor(Role.STUDENT), None)
