"""Terms and bells (ADM-8, ADM-18, UF-ADM-05)."""

import datetime as dt
from typing import Any

from app.modules.academic.application.schedule.results import TermData
from app.modules.academic.domain.schedule.errors import (
    TermBellsInvalidError,
    TermControlPeriodsInvalidError,
    TermDuplicateError,
    TermMovedDayInvalidError,
    TermNotFoundError,
    TermOverlapError,
)
from app.modules.academic.domain.schedule.term import (
    Bell,
    ControlPeriod,
    ControlPeriods,
    MovedDay,
)
from app.shared.ids import new_id
from tests.academic.schedule.env import TERM_END, TERM_START, Env, default_bells

import pytest


async def create(env: Env, **overrides: Any) -> TermData:
    """Create the default term through the use case."""
    fields: dict[str, Any] = {
        "academic_year": "2026-2027",
        "half": 1,
        "starts_on": TERM_START,
        "ends_on": TERM_END,
        "bells": default_bells(),
        "non_study_days": [],
        "moved_days": [],
    }
    fields.update(overrides)
    return await env.services.create_term.execute(**fields)


async def test_a_created_term_is_listed_and_current(env: Env) -> None:
    """ADM-8: the term containing today is flagged as current."""
    created = await create(env, non_study_days=[dt.date(2026, 10, 12)])

    terms = await env.services.list_terms.execute()

    assert [t.id for t in terms] == [created.id]
    assert terms[0].is_current is True
    assert terms[0].non_study_days == [dt.date(2026, 10, 12)]
    assert terms[0].bells == default_bells()


async def test_terms_cannot_overlap(env: Env) -> None:
    """ACA-4 / ADM-8: two terms never share a day."""
    await create(env)

    with pytest.raises(TermOverlapError):
        await create(
            env,
            academic_year="2026-2027",
            half=2,
            starts_on=dt.date(2026, 12, 25),
            ends_on=dt.date(2027, 5, 30),
        )


async def test_adjacent_terms_are_fine(env: Env) -> None:
    """ADM-8: the second half starts after the first one ends."""
    await create(env)

    second = await create(
        env, half=2, starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30)
    )

    assert second.is_current is False


async def test_academic_year_and_half_are_unique(env: Env) -> None:
    """README -> Term: academic_year + half is unique."""
    await create(env)

    with pytest.raises(TermDuplicateError):
        await create(env, starts_on=dt.date(2028, 9, 1), ends_on=dt.date(2028, 12, 25))


async def test_invalid_bells_are_rejected(env: Env) -> None:
    """ADM-8: a period appears once per weekday."""
    twice = [
        Bell(period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1]),
        Bell(period=1, start=dt.time(8, 0), end=dt.time(8, 45), weekdays=[1]),
    ]

    with pytest.raises(TermBellsInvalidError):
        await create(env, bells=twice)


async def test_updating_a_term_changes_bells_and_regenerates_lessons(env: Env) -> None:
    """UF-ADM-05 2a: new period times reach future lessons."""
    term = await create(env)
    shifted = [
        Bell(
            period=1, start=dt.time(9, 0), end=dt.time(9, 45), weekdays=[1, 2, 3, 4, 5]
        )
    ]

    updated = await env.services.update_term.execute(term.id, bells=shifted)

    assert updated.bells == shifted
    assert updated.starts_on == TERM_START
    assert env.kicker.calls == [
        (
            "academic.generate_lessons",
            {"term_id": str(term.id), "from_date": "2026-10-06"},
        )
    ]


async def test_a_moved_day_can_be_added_later(env: Env) -> None:
    """ADM-18: 'Friday 13.11 follows Monday'."""
    term = await create(env)
    moved = [MovedDay(date=dt.date(2026, 11, 13), follows_weekday=1)]

    updated = await env.services.update_term.execute(term.id, moved_days=moved)

    assert updated.moved_days == moved


async def test_a_moved_day_cannot_be_a_saturday(env: Env) -> None:
    """The lyceum does not study on Saturdays, not even on a moved day."""
    term = await create(env)
    moved = [MovedDay(date=dt.date(2026, 11, 14), follows_weekday=1)]

    with pytest.raises(TermMovedDayInvalidError):
        await env.services.update_term.execute(term.id, moved_days=moved)


async def test_control_periods_are_set_on_create_and_changed_on_update(
    env: Env,
) -> None:
    """The admin sets the midterm and final weeks of the term."""
    midterm_1 = ControlPeriod(start=dt.date(2026, 10, 20), end=dt.date(2026, 10, 25))
    created = await create(env, control_periods=ControlPeriods(midterm_1=midterm_1))
    assert created.control_periods.midterm_1 == midterm_1
    assert created.control_periods.final is None

    final = ControlPeriod(start=dt.date(2026, 12, 14), end=dt.date(2026, 12, 19))
    updated = await env.services.update_term.execute(
        created.id, control_periods=ControlPeriods(midterm_1=midterm_1, final=final)
    )

    assert updated.control_periods == ControlPeriods(midterm_1=midterm_1, final=final)
    (listed,) = await env.services.list_terms.execute()
    assert listed.control_periods == updated.control_periods


async def test_control_periods_outside_the_term_are_rejected(env: Env) -> None:
    """A control week must lie inside the term."""
    outside = ControlPeriod(start=dt.date(2027, 1, 10), end=dt.date(2027, 1, 15))

    with pytest.raises(TermControlPeriodsInvalidError):
        await create(env, control_periods=ControlPeriods(final=outside))


async def test_updating_cannot_make_a_term_overlap_another(env: Env) -> None:
    """ADM-8: the overlap check also runs on update."""
    await create(env)
    second = await create(
        env, half=2, starts_on=dt.date(2027, 1, 11), ends_on=dt.date(2027, 5, 30)
    )

    with pytest.raises(TermOverlapError):
        await env.services.update_term.execute(
            second.id, starts_on=dt.date(2026, 12, 1)
        )


async def test_updating_an_unknown_term_is_not_found(env: Env) -> None:
    """ADM-8: unknown ids answer 404."""
    with pytest.raises(TermNotFoundError):
        await env.services.update_term.execute(new_id(), half=2)


async def test_the_current_term_falls_back_to_the_next_one(env: Env) -> None:
    """ADM-8: before a term starts, it is the current one."""
    await create(env, starts_on=dt.date(2026, 11, 1), ends_on=dt.date(2026, 12, 25))

    current = await env.services.current_term.execute()

    assert current is not None and current.starts_on == dt.date(2026, 11, 1)


async def test_without_terms_there_is_no_current_term(env: Env) -> None:
    """ADM-8: nothing to find."""
    assert await env.services.current_term.execute() is None
