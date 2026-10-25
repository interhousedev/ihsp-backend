"""ScheduleOverview and AttendanceStats over fake schedule and classwork use cases."""

import datetime as dt
from uuid import UUID

from app.bootstrap.adapters.composition.attendance_stats import AttendanceStatsAdapter
from app.bootstrap.adapters.composition.schedule_overview import (
    ScheduleOverviewAdapter,
)
from app.interfaces.http.v1.composition.ports import DayCounts
from app.modules.academic.application.schedule.ports.reader import LessonFilters
from app.modules.academic.application.schedule.results import LessonItemsPage
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.bootstrap.composition.data import (
    lesson_json,
    make_group_data,
    make_term_data,
    person_json,
)
from tests.bootstrap.composition.fakes import FakeUseCase
from tests.factories import make_actor

DAY = dt.date(2026, 10, 6)


def overview(
    term: object = None, lessons: object = None, groups: object = None
) -> ScheduleOverviewAdapter:
    """The adapter over fakes."""
    return ScheduleOverviewAdapter(
        FakeUseCase(term),  # type: ignore[arg-type]
        lessons or FakeUseCase(),  # type: ignore[arg-type]
        FakeUseCase(groups or []),  # type: ignore[arg-type]
    )


async def test_term_bounds_are_the_start_and_end_of_the_current_term() -> None:
    """`CurrentTerm` answers for the day; the bounds are its dates."""
    current_term = FakeUseCase(make_term_data())
    adapter = ScheduleOverviewAdapter(
        current_term,  # type: ignore[arg-type]
        FakeUseCase(),  # type: ignore[arg-type]
        FakeUseCase(),  # type: ignore[arg-type]
    )

    assert await adapter.term_bounds(DAY) == (
        dt.date(2026, 9, 2),
        dt.date(2026, 12, 30),
    )
    assert current_term.calls == [((DAY,), {})]


async def test_term_bounds_are_none_without_a_term() -> None:
    """No term at all: None."""
    assert await overview(term=None).term_bounds(DAY) is None


async def test_day_counts_count_lessons_cancelled_and_teacherless_over_pages() -> None:
    """Cancelled ones count as lessons too; only scheduled lessons need a teacher."""
    teacher = person_json()
    first = LessonItemsPage(
        items=[
            lesson_json(teacher=teacher),
            lesson_json(teacher=None),
            lesson_json(status="cancelled", teacher=None),
        ],
        next_cursor="page-2",
    )
    second = LessonItemsPage(
        items=[
            lesson_json(status="cancelled", teacher=teacher),
            lesson_json(teacher=None),
        ],
        next_cursor=None,
    )
    listing = FakeUseCase(first, second)
    actor = make_actor(Role.ADMIN)

    counts = await overview(lessons=listing).day_counts(actor, DAY)

    assert counts == DayCounts(lessons=5, cancelled=2, teacher_needed=2)
    (call_actor, filters), kwargs = listing.calls[0]
    assert call_actor is actor
    assert filters == LessonFilters(start=DAY, end=DAY)
    assert kwargs == {"cursor": None, "limit": 100}
    assert listing.calls[1][1]["cursor"] == "page-2"


async def test_day_counts_of_an_empty_day_are_zero() -> None:
    """A holiday has no lessons."""
    empty = LessonItemsPage(items=[], next_cursor=None)

    counts = await overview(lessons=FakeUseCase(empty)).day_counts(
        make_actor(Role.ADMIN), DAY
    )

    assert counts == DayCounts(lessons=0, cancelled=0, teacher_needed=0)


async def test_active_group_ids_ask_for_active_groups_only() -> None:
    """The adapter lists the groups with status `active` and returns their ids."""
    groups = [make_group_data("2TN2"), make_group_data("1TN1")]
    list_groups = FakeUseCase(groups)
    adapter = ScheduleOverviewAdapter(
        FakeUseCase(),  # type: ignore[arg-type]
        FakeUseCase(),  # type: ignore[arg-type]
        list_groups,  # type: ignore[arg-type]
    )

    assert await adapter.active_group_ids() == [g.id for g in groups]
    assert list_groups.calls == [(("active",), {})]


async def test_group_absence_rates_come_from_the_group_report() -> None:
    """One rate per row of the `view=group` report, `None` when nothing was taken."""
    busy, quiet = new_id(), new_id()
    report = {
        "view": "group",
        "from": "2026-09-01",
        "to": "2026-10-06",
        "rows": [
            {"key": str(busy), "label": "2TN2", "absences": 3, "excused": 1,
             "lessons": 40, "rate": 0.075, "not_taken": 0},
            {"key": str(quiet), "label": "1TN1", "absences": 0, "excused": 0,
             "lessons": 0, "rate": None, "not_taken": 2},
        ],
    }  # fmt: skip
    attendance_report = FakeUseCase(report)
    stats = AttendanceStatsAdapter(attendance_report)  # type: ignore[arg-type]
    actor = make_actor(Role.ADMIN)

    rates = await stats.group_absence_rates(actor, dt.date(2026, 9, 1), DAY)

    assert rates == {busy: 0.075, quiet: None}
    assert all(isinstance(key, UUID) for key in rates)
    assert attendance_report.calls == [
        ((actor, "group", dt.date(2026, 9, 1), DAY, None), {})
    ]
