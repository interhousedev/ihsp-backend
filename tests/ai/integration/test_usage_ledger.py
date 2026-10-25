"""The usage ledger on the test database: writes, aggregates, retention, report."""

from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

from app.modules.ai.application.purge_usage_events import PurgeUsageEvents
from app.modules.ai.application.usage_report import UsageRangeInvalidError, UsageReport
from app.modules.ai.domain.usage import UsageEvent
from app.modules.ai.infrastructure.usage_reader import SqlUsageReader
from app.modules.ai.infrastructure.usage_store import SqlUsageStore
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock
from tests.fakes.notify.identity import FakeIdentityDirectory

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

WIDE_START = datetime(2026, 1, 1, tzinfo=UTC)
WIDE_END = datetime(2027, 1, 1, tzinfo=UTC)
NOON_TASHKENT_OF_OCT_9 = datetime(2026, 10, 9, 5, 0, tzinfo=UTC)


def event(**changes: Any) -> UsageEvent:
    values: dict[str, Any] = {
        "occurred_at": NOON_TASHKENT_OF_OCT_9,
        "user_id": None,
        "role": "student",
        "task": "student_chat",
        "feature": "assistant",
        "model": "anthropic/claude-haiku-5.5",
        "input_tokens": 100,
        "output_tokens": 20,
        "cached_tokens": 0,
        "reasoning_tokens": None,
        "cost_micro": 1000,
        "success": True,
        "error": None,
    }
    values.update(changes)
    return UsageEvent(**values)


@pytest.fixture
def ledger(
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
) -> tuple[SqlUsageStore, SqlUsageReader]:
    return SqlUsageStore(sessionmaker_in_tx), SqlUsageReader(sessionmaker_in_tx)


async def test_events_are_grouped_by_tashkent_day_task_model_role_and_feature(
    ledger: tuple[SqlUsageStore, SqlUsageReader],
) -> None:
    store, reader = ledger
    aziza = uuid4()
    await store.write(event(user_id=aziza))
    # 22:00 UTC is already the next day in Tashkent (UTC+5).
    await store.write(
        event(user_id=aziza, occurred_at=datetime(2026, 10, 9, 22, 0, tzinfo=UTC))
    )
    await store.write(
        event(
            user_id=uuid4(),
            role="teacher",
            task="studio_quiz",
            feature="studio",
            model="anthropic/claude-sonnet-5.5",
            cost_micro=5000,
            success=False,
            input_tokens=200,
        )
    )

    totals = await reader.totals(WIDE_START, WIDE_END)
    assert (totals.calls, totals.failed, totals.cost_micro) == (3, 1, 7000)
    assert totals.tokens_in == 400

    by_day = await reader.grouped(WIDE_START, WIDE_END, "day")
    assert [(g.key, g.totals.calls) for g in by_day if g.feature == "assistant"] == [
        ("2026-10-09", 1),
        ("2026-10-10", 1),
    ]
    by_task = {
        (g.key, g.feature): g.totals.cost_micro
        for g in await reader.grouped(WIDE_START, WIDE_END, "task")
    }
    assert by_task == {
        ("student_chat", "assistant"): 2000,
        ("studio_quiz", "studio"): 5000,
    }
    by_role = {
        g.key: g.totals.calls
        for g in await reader.grouped(WIDE_START, WIDE_END, "role")
    }
    assert by_role == {"student": 2, "teacher": 1}
    by_model = {
        g.key: g.totals.cost_micro
        for g in await reader.grouped(WIDE_START, WIDE_END, "model")
    }
    assert by_model == {
        "anthropic/claude-haiku-5.5": 2000,
        "anthropic/claude-sonnet-5.5": 5000,
    }
    by_feature = {
        g.key: g.totals.cost_micro
        for g in await reader.grouped(WIDE_START, WIDE_END, "feature")
    }
    assert by_feature == {"assistant": 2000, "studio": 5000}


async def test_top_users_are_ranked_by_cost_with_the_role_of_their_latest_call(
    ledger: tuple[SqlUsageStore, SqlUsageReader],
) -> None:
    store, reader = ledger
    aziza, lecturer = uuid4(), uuid4()
    await store.write(event(user_id=aziza, cost_micro=1000))
    await store.write(event(user_id=aziza, cost_micro=1000))
    await store.write(event(user_id=lecturer, role="teacher", cost_micro=5000))
    await store.write(
        event(user_id=None, cost_micro=9000)
    )  # system calls are not users

    top = await reader.top_users(WIDE_START, WIDE_END, 20)

    assert [(row.user_id, row.role, row.totals.cost_micro) for row in top] == [
        (lecturer, "teacher", 5000),
        (aziza, "student", 2000),
    ]


async def test_retention_removes_only_the_events_before_the_window(
    ledger: tuple[SqlUsageStore, SqlUsageReader],
) -> None:
    store, reader = ledger
    clock = FixedClock(datetime(2026, 10, 6, 9, 0, tzinfo=UTC))
    await store.write(event(occurred_at=datetime(2025, 8, 1, tzinfo=UTC)))
    await store.write(event(occurred_at=datetime(2026, 10, 5, tzinfo=UTC)))

    removed = await PurgeUsageEvents(
        store=store, clock=clock, retention_days=400
    ).execute()

    assert removed == 1
    assert (await reader.totals(WIDE_START, WIDE_END)).calls == 1


async def test_the_report_projects_the_month_names_the_top_users_and_fills_the_days(
    ledger: tuple[SqlUsageStore, SqlUsageReader],
) -> None:
    store, reader = ledger
    identity = FakeIdentityDirectory()
    admin = identity.add_user(make_user(Role.ADMIN), 900)
    aziza_id = uuid4()
    identity.add_user(
        make_user(
            Role.STUDENT, first_name="Aziza", last_name="Karimova", user_id=aziza_id
        ),
        901,
    )
    await store.write(
        event(
            user_id=aziza_id,
            occurred_at=datetime(2026, 10, 1, 4, 0, tzinfo=UTC),
            cost_micro=2_000_000,
        )
    )
    await store.write(
        event(
            user_id=aziza_id,
            occurred_at=datetime(2026, 10, 11, 4, 0, tzinfo=UTC),
            cost_micro=1_000_000,
        )
    )
    report = UsageReport(
        reader=reader,
        identity=identity,
        clock=FixedClock(datetime(2026, 10, 11, 9, 0, tzinfo=UTC)),
    )
    actor = Actor(user_id=admin.id, roles=frozenset({Role.ADMIN}))

    view = await report.execute(
        actor, from_day=date(2026, 10, 9), to_day=date(2026, 10, 11), group_by="day"
    )

    assert [row.key for row in view.rows] == ["2026-10-09", "2026-10-10", "2026-10-11"]
    assert view.rows[0].totals.calls == 0
    assert view.rows[2].totals.cost_micro == 1_000_000
    assert view.month.month == "2026-10"
    assert view.month.cost_micro == 3_000_000
    assert view.month.days_elapsed == 11
    assert view.month.days_in_month == 31
    assert view.month.projected_micro == 3_000_000 * 31 // 11
    assert view.today.calls == 1
    assert view.top_users[0].name == "Aziza Karimova"
    assert view.top_users[0].user_id == aziza_id


async def test_the_report_is_for_administration_and_has_a_range_limit(
    ledger: tuple[SqlUsageStore, SqlUsageReader],
) -> None:
    _, reader = ledger
    report = UsageReport(
        reader=reader, identity=FakeIdentityDirectory(), clock=FixedClock()
    )
    student = Actor(user_id=UUID(int=1), roles=frozenset({Role.STUDENT}))
    admin = Actor(user_id=UUID(int=2), roles=frozenset({Role.ADMIN}))

    with pytest.raises(ForbiddenError):
        await report.execute(student)
    with pytest.raises(UsageRangeInvalidError):
        await report.execute(
            admin, from_day=date(2025, 1, 1), to_day=date(2026, 10, 11)
        )
    with pytest.raises(UsageRangeInvalidError):
        await report.execute(
            admin, from_day=date(2026, 10, 11), to_day=date(2026, 10, 1)
        )
