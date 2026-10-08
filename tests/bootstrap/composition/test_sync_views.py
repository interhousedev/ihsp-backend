"""SyncViews: `students.sync_failures` on PostgreSQL and the newest sync run."""

import datetime as dt
from collections.abc import Callable
from typing import Any

from app.bootstrap.adapters.composition.sync_views import SyncViewsAdapter
from app.interfaces.http.v1.composition.admin_schemas import SyncRunItemResponse
from app.modules.academic.application.marks.get_sync_failures import GetSyncFailures
from app.modules.academic.infrastructure.marks.uow import SqlMarksUnitOfWork
from app.shared.actor import Role
from app.shared.ids import new_id
from app.shared.pagination import Page
from tests.academic.schedule.env import Env
from tests.bootstrap.composition.fakes import FakeUseCase
from tests.factories import make_actor

UowFactory = Callable[[], SqlMarksUnitOfWork]


async def record_failure(factory: UowFactory, user_id: Any) -> None:
    """Count one more failed sync of the student."""
    async with factory() as uow:
        await uow.students.record_failure(user_id, error="EMIS is down")
        await uow.commit()


async def test_sync_failures_counts_consecutive_failures(
    sql_env: Env, marks_uow_factory: UowFactory
) -> None:
    """Every failed sync adds one; a success resets the count to zero."""
    student = await sql_env.student(await sql_env.group())
    use_case = GetSyncFailures(uow_factory=marks_uow_factory)
    assert await use_case.execute(student.id) == 0

    await record_failure(marks_uow_factory, student.id)
    await record_failure(marks_uow_factory, student.id)
    assert await use_case.execute(student.id) == 2

    async with marks_uow_factory() as uow:
        await uow.students.record_success(
            student.id, at=dt.datetime(2026, 10, 6, tzinfo=dt.UTC), backfilled=False
        )
        await uow.commit()
    assert await use_case.execute(student.id) == 0


async def test_sync_failures_of_a_non_student_is_zero(
    marks_uow_factory: UowFactory,
) -> None:
    """A user without a student row has no failures."""
    use_case = GetSyncFailures(uow_factory=marks_uow_factory)

    assert await use_case.execute(new_id()) == 0


async def test_adapter_reports_failures_from_the_marks_use_case(
    sql_env: Env, marks_uow_factory: UowFactory
) -> None:
    """`SyncViews.sync_failures` over the real use case."""
    student = await sql_env.student(await sql_env.group())
    await record_failure(marks_uow_factory, student.id)
    adapter = SyncViewsAdapter(
        GetSyncFailures(uow_factory=marks_uow_factory),
        FakeUseCase(Page[dict[str, Any]](items=[])),  # type: ignore[arg-type]
    )

    assert await adapter.sync_failures(student.id) == 1


async def test_last_sync_run_is_the_first_row_as_json() -> None:
    """The newest run comes back as a `SyncRunItem`, asked with limit 1."""
    started = dt.datetime(2026, 10, 6, 6, 30, tzinfo=dt.UTC)
    run = {
        "id": new_id(),
        "started_at": started,
        "finished_at": started + dt.timedelta(minutes=4),
        "status": "ok",
        "stats": {"students": 120, "marks_new": 34},
    }
    list_runs = FakeUseCase(Page[dict[str, Any]](items=[run], next_cursor="more"))
    adapter = SyncViewsAdapter(FakeUseCase(0), list_runs)  # type: ignore[arg-type]
    actor = make_actor(Role.ADMIN)

    result = await adapter.last_sync_run(actor)

    assert list_runs.calls == [((actor, None, 1), {})]
    assert result is not None
    assert result["id"] == str(run["id"])
    assert result["started_at"] == "2026-10-06T06:30:00Z"
    item = SyncRunItemResponse.model_validate(result)
    assert item.status == "ok"
    assert item.stats == {"students": 120, "marks_new": 34}


async def test_last_sync_run_is_none_before_the_first_run() -> None:
    """No run yet: the dashboard shows an empty state."""
    adapter = SyncViewsAdapter(
        FakeUseCase(0),  # type: ignore[arg-type]
        FakeUseCase(Page[dict[str, Any]](items=[])),  # type: ignore[arg-type]
    )

    assert await adapter.last_sync_run(make_actor(Role.ADMIN)) is None
