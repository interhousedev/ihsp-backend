"""ACA-4, ACA-7: a weekday whose lessons have other times than the rest of the week.

The sample is made up: nobody has seen how EMIS lists a different Friday.
"""

import datetime as dt
from types import SimpleNamespace
from typing import cast
from uuid import UUID

from app.interfaces.mcp.student.views import lesson_view
from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    bell_or_nearest,
    lesson_times,
)
from app.modules.academic.domain.schedule.generation import expand_entries
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.term import Bell
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.modules.ai.application.tools.format import lesson_dict
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id
from tests.academic.schedule.builders import make_term
from tests.academic.schedule.emis_builders import PHYSICS, day, klass, weekly
from tests.academic.schedule.env import Env

FRIDAY_START = dt.time(9, 50)
FRIDAY_END = dt.time(10, 30)


def different_friday() -> list[Bell]:
    """Period 1 is the same all week; period 2 is later on Friday."""
    return [
        Bell(
            period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2, 3, 4, 5]
        ),
        Bell(
            period=2, start=dt.time(9, 25), end=dt.time(10, 10), weekdays=[1, 2, 3, 4]
        ),
        Bell(period=2, start=FRIDAY_START, end=FRIDAY_END, weekdays=[5]),
        Bell(
            period=3,
            start=dt.time(10, 40),
            end=dt.time(11, 25),
            weekdays=[1, 2, 3, 4, 5],
        ),
    ]


def no_friday_second() -> list[Bell]:
    """Period 2 has no Friday block at all."""
    return [b for b in different_friday() if not (b.period == 2 and b.weekdays == [5])]


async def synced(env: Env, bells: list[Bell]) -> tuple[UUID, UUID]:
    """A term with the bells, one group and one student; returns their ids."""
    await env.term(bells=bells)
    group = await env.group("2TN2", emis_group_id=3292)
    user = await env.student(group)
    return group.id, user.id


async def run(env: Env, ids: tuple[UUID, UUID]) -> None:
    await env.emis_import.sync_group_timetable.execute(
        group_id=ids[0], user_id=ids[1], refresh_bells=False
    )


async def on_day(env: Env, when: dt.date) -> list[Lesson]:
    found = [x for x in await env.lessons() if x.date == when]
    return sorted(found, key=lambda x: x.period)


def test_a_model_reads_the_lessons_own_friday_time_and_status() -> None:
    """MCP and the AI tools give each lesson its Tashkent time, not one per period."""
    starts_at, ends_at = lesson_times(day(1, 5), FRIDAY_START, FRIDAY_END)
    ref = cast(
        LessonRef,
        SimpleNamespace(
            id=new_id(),
            date=day(1, 5),
            period=2,
            starts_at=starts_at,
            ends_at=ends_at,
            subject_id=new_id(),
            subject_name="Math",
            teacher_id=None,
            room_name=None,
            group_names=(),
            status="scheduled",
            topic=None,
            homework_text=None,
            homework_due_date=None,
        ),
    )

    view = lesson_view(ref)
    shown = lesson_dict(ref)

    assert (view["start_local"], view["end_local"], view["status"]) == (
        "09:50",
        "10:30",
        "scheduled",
    )
    assert (shown["start"], shown["end"], shown["status"]) == (
        "09:50",
        "10:30",
        "scheduled",
    )


def test_a_missing_bell_borrows_the_nearest_weekday() -> None:
    """The same period on the closest day; a period nobody has stays unknown."""
    term = make_term(bells=no_friday_second())

    assert bell_for(term, 2, 5) is None
    assert bell_or_nearest(term, 2, 5) == (dt.time(9, 25), dt.time(10, 10))
    assert bell_or_nearest(term, 9, 5) is None


def test_an_emis_entry_is_planned_without_a_bell_and_a_manual_one_is_not() -> None:
    """EMIS lists the class, so it stays; Administration removed the manual block."""
    term = make_term(bells=no_friday_second())
    made = [
        TimetableEntry(
            id=new_id(),
            term_id=term.id,
            weekday=5,
            period=2,
            week_parity="every",
            subject_id=new_id(),
            teacher_id=None,
            room_id=None,
            audience=["a"],
            valid_from=term.starts_on,
            source=source,
        )
        for source in ("emis", "manual")
    ]
    friday = day(1, 5)

    expansion = expand_entries(term, made, friday, friday)

    assert [key[0] for key in expansion.planned] == [made[0].id]
    assert made[1].id in expansion.missing_bells


async def test_friday_period_two_has_its_own_time_and_is_scheduled(env: Env) -> None:
    """The reported case: the same class pair, a different Friday time."""
    ids = await synced(env, different_friday())
    env.emis.classes = weekly(4, 1, subject=PHYSICS) + weekly(5, 1)

    await run(env, ids)
    await run(env, ids)

    thursday = (await on_day(env, day(1, 4)))[0]
    friday = (await on_day(env, day(1, 5)))[0]
    assert (thursday.status, friday.status) == ("scheduled", "scheduled")
    assert (friday.starts_at, friday.ends_at) == lesson_times(
        day(1, 5), FRIDAY_START, FRIDAY_END
    )
    assert thursday.starts_at.time() != friday.starts_at.time()


async def test_a_friday_without_the_bell_keeps_the_class_at_a_borrowed_time(
    env: Env,
) -> None:
    """A class EMIS lists is neither skipped nor cancelled, even a brand-new one."""
    ids = await synced(env, no_friday_second())
    env.emis.classes = weekly(5, 1) + [klass(2, 5, 2, class_id=555, subject=PHYSICS)]

    await run(env, ids)
    await run(env, ids)

    friday = await on_day(env, day(1, 5))
    assert [(x.period, x.status) for x in friday] == [(2, "scheduled")]
    assert (
        friday[0].starts_at
        == lesson_times(day(1, 5), dt.time(9, 25), dt.time(10, 10))[0]
    )


async def test_a_class_moved_to_another_pair_on_friday_is_not_cancelled(
    env: Env,
) -> None:
    """Week after week at another pair: a single scheduled lesson, nothing cancelled."""
    ids = await synced(env, different_friday())
    listed = weekly(5, 0)
    env.emis.classes = listed
    await run(env, ids)
    before = (await on_day(env, day(1, 5)))[0]
    await env.give_homework(before.id)
    env.emis.classes = [
        klass(week, 5, 1, class_id=c.class_id)
        for week, c in zip((0, 1, 2, 3), listed, strict=True)
    ]

    await run(env, ids)

    friday = await on_day(env, day(1, 5))
    assert [(x.id, x.period, x.status) for x in friday] == [(before.id, 2, "scheduled")]
    assert friday[0].starts_at == lesson_times(day(1, 5), FRIDAY_START, FRIDAY_END)[0]
    assert "status" not in (friday[0].changes or {})


async def test_a_class_listed_again_at_another_pair_is_revived(env: Env) -> None:
    """A cancellation EMIS caused is undone when the class returns somewhere else."""
    ids = await synced(env, different_friday())
    env.emis.classes = weekly(5, 0)
    await run(env, ids)
    friday = (await on_day(env, day(1, 5)))[0]
    env.emis.classes = [c for c in weekly(5, 0) if c.date != day(1, 5)]
    await run(env, ids)
    assert (await on_day(env, day(1, 5)))[0].status == "cancelled"
    env.emis.classes = [c for c in weekly(5, 0) if c.date != day(1, 5)] + [
        klass(1, 5, 1, class_id=friday.emis_class_id)
    ]

    await run(env, ids)

    after = await on_day(env, day(1, 5))
    assert [(x.id, x.period, x.status) for x in after] == [(friday.id, 2, "scheduled")]
    assert "status" not in (after[0].changes or {})


async def test_a_listed_class_that_could_not_move_stays_scheduled(env: Env) -> None:
    """A pair no weekday has gives no time: the lesson keeps its own, not cancelled."""
    ids = await synced(env, different_friday())
    env.emis.classes = weekly(5, 0)
    await run(env, ids)
    friday = (await on_day(env, day(1, 5)))[0]
    env.emis.classes = [c for c in weekly(5, 0) if c.date != day(1, 5)] + [
        klass(1, 5, 8, class_id=friday.emis_class_id)
    ]

    await run(env, ids)

    after = await on_day(env, day(1, 5))
    assert [(x.id, x.period, x.status) for x in after] == [(friday.id, 1, "scheduled")]


async def test_a_moved_lesson_follows_a_later_change_of_the_friday_bell(
    env: Env,
) -> None:
    """A lesson EMIS moved is overridden, the generator leaves it: the sync aligns."""
    ids = await synced(env, different_friday())
    env.emis.classes = weekly(5, 0)
    await run(env, ids)
    friday = (await on_day(env, day(1, 5)))[0]
    only = [c for c in weekly(5, 0) if c.date != day(1, 5)]
    env.emis.classes = [*only, klass(1, 5, 1, class_id=friday.emis_class_id)]
    await run(env, ids)
    async with env.uow_factory() as uow:
        term = await uow.terms.get(friday.term_id)
        assert term is not None
        term.bells = [
            (
                b.model_copy(update={"start": dt.time(10, 0), "end": dt.time(10, 35)})
                if b.period == 2 and b.weekdays == [5]
                else b
            )
            for b in term.bells
        ]
        await uow.terms.save(term)
        await uow.commit()

    await run(env, ids)

    after = (await on_day(env, day(1, 5)))[0]
    assert (
        after.starts_at == lesson_times(day(1, 5), dt.time(10, 0), dt.time(10, 35))[0]
    )
