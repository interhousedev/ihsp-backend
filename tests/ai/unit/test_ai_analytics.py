"""AiAnalytics: admin only, range rules, totals, names of users."""

from datetime import date
from types import SimpleNamespace
from uuid import UUID

from app.modules.ai.application.ai_analytics import AiAnalytics, AiRangeTooLargeError
from app.modules.ai.ports.analytics import (
    RequestStatsRow,
    SpendDailyRow,
    SpendRow,
)
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest

ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
TEACHER = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
USER = UUID(int=7)


class FakeReader:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    async def request_stats(self, *args: object) -> list[RequestStatsRow]:
        self.calls.append(("request_stats", args))
        return [
            RequestStatsRow("a", 1, 0, 100.0, 400.0, 10.0, 5.0, 1.0, 100),
            RequestStatsRow("b", 3, 1, 200.0, 800.0, 30.0, 9.0, 0.0, 300),
        ]

    async def spend(self, *args: object) -> list[SpendRow]:
        self.calls.append(("spend", args))
        return [SpendRow(str(USER), 500, 4, 1, USER)]

    async def spend_daily(self, *args: object) -> list[SpendDailyRow]:
        self.calls.append(("spend_daily", args))
        return [SpendDailyRow("2026-10-05", "other", 5, 1)]


class FakeIdentity:
    async def get_users(self, ids: list[UUID]) -> dict[UUID, object]:
        return {
            i: SimpleNamespace(
                first_name="Ali", last_name="V", roles=frozenset({Role.STUDENT})
            )
            for i in ids
        }


@pytest.fixture
def reader() -> FakeReader:
    return FakeReader()


@pytest.fixture
def analytics(reader: FakeReader) -> AiAnalytics:
    return AiAnalytics(
        reader=reader,
        identity=FakeIdentity(),  # type: ignore[arg-type]
        clock=FixedClock(),
    )


async def test_totals_weight_the_averages_by_calls(analytics: AiAnalytics) -> None:
    out = await analytics.request_stats(ADMIN)

    totals = out["totals"]
    assert totals["calls"] == 4
    assert totals["failed"] == 1
    assert totals["cost_micro"] == 400
    assert totals["avg_prompt_tokens"] == pytest.approx(175.0)


async def test_the_default_range_is_the_last_30_days(
    analytics: AiAnalytics, reader: FakeReader
) -> None:
    await analytics.request_stats(ADMIN)

    start, end = reader.calls[0][1][:2]
    assert end == date(2026, 10, 6)
    assert start == date(2026, 9, 7)


async def test_a_range_over_400_days_is_refused(analytics: AiAnalytics) -> None:
    with pytest.raises(AiRangeTooLargeError):
        await analytics.spend(ADMIN, start=date(2025, 1, 1), end=date(2026, 10, 6))


async def test_spend_by_user_names_the_user(analytics: AiAnalytics) -> None:
    out = await analytics.spend(ADMIN, by="user")

    assert out["total_cost_micro"] == 500
    assert out["items"][0]["user"] == {
        "id": str(USER),
        "full_name": "Ali V",
        "role": "student",
    }


async def test_spend_by_day_has_no_user(analytics: AiAnalytics) -> None:
    out = await analytics.spend(ADMIN, by="day")

    assert out["items"][0]["user"] is None


async def test_daily_matrix_passes_through(analytics: AiAnalytics) -> None:
    out = await analytics.spend_daily(ADMIN)

    assert out["items"] == [
        {"day": "2026-10-05", "request_id": "other", "cost_micro": 5, "calls": 1}
    ]


async def test_only_admins_read(analytics: AiAnalytics) -> None:
    with pytest.raises(ForbiddenError):
        await analytics.request_stats(TEACHER)
