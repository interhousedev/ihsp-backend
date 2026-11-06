"""ACA-4: every weekday, weekend included, has its own column of lesson blocks."""

import datetime as dt

from app.modules.academic.application.schedule.update_entry import EntryPatch
from app.modules.academic.domain.schedule.calendar import (
    bell_for,
    effective_weekday,
)
from app.modules.academic.domain.schedule.emis_bells import (
    bells_from_class_hours,
    merge_emis_bells,
)
from app.modules.academic.domain.schedule.errors import (
    EntryNotSchoolDayError,
    NoBellError,
    TermBellsInvalidError,
)
from app.modules.academic.domain.schedule.term import Bell, Term, validate_term
from app.modules.identity.infrastructure.emis.fake import FAKE_CLASS_HOURS
from app.shared.actor import Role
from app.shared.ids import new_id
from tests.academic.schedule.builders import entry_input
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)
MONDAY = dt.date(2026, 11, 9)
TUESDAY = dt.date(2026, 11, 10)
FRIDAY = dt.date(2026, 11, 13)
SATURDAY = dt.date(2026, 11, 14)
SUNDAY = dt.date(2026, 11, 15)
TERM_START = dt.date(2026, 9, 1)
TERM_END = dt.date(2026, 12, 25)


def block(
    period: int, start: tuple[int, int], end: tuple[int, int], days: list[int]
) -> Bell:
    """One lesson block by hand."""
    return Bell(period=period, start=dt.time(*start), end=dt.time(*end), weekdays=days)


def term_with(bells: list[Bell]) -> Term:
    """A term of the autumn with these blocks."""
    return Term(
        id=new_id(),
        academic_year="2026-2027",
        half=1,
        starts_on=TERM_START,
        ends_on=TERM_END,
        bells=bells,
    )


WEEK = [
    block(2, (10, 10), (11, 30), [1]),
    block(2, (11, 0), (12, 20), [2]),
    block(2, (9, 0), (9, 40), [5]),
    block(1, (9, 0), (10, 0), [6]),
]


def test_the_same_lesson_has_the_time_of_its_day() -> None:
    """Lesson 2 is 10:10 on Monday and 11:00 on Tuesday."""
    term = term_with(WEEK)

    assert bell_for(term, 2, 1) == (dt.time(10, 10), dt.time(11, 30))
    assert bell_for(term, 2, 2) == (dt.time(11, 0), dt.time(12, 20))
    assert bell_for(term, 2, 3) is None


def test_saturday_and_sunday_may_have_blocks_or_none() -> None:
    """A weekend day with blocks is a study day; without them it is not."""
    term = term_with(WEEK)

    validate_term(term)
    assert effective_weekday(SATURDAY, term) == 6
    assert effective_weekday(SUNDAY, term) is None


def test_a_non_study_saturday_with_blocks_stays_free() -> None:
    """A holiday wins over the blocks of its day."""
    term = term_with(WEEK)
    term.non_study_days = [SATURDAY]

    assert effective_weekday(SATURDAY, term) is None


def test_blocks_of_one_day_may_not_overlap() -> None:
    """Two lessons of a day cannot share time."""
    term = term_with([block(1, (9, 0), (10, 0), [5]), block(2, (9, 30), (10, 30), [5])])

    with pytest.raises(TermBellsInvalidError):
        validate_term(term)


def test_blocks_of_different_days_may_overlap() -> None:
    """Only the blocks of the same day are compared."""
    validate_term(
        term_with([block(1, (9, 0), (10, 0), [4]), block(2, (9, 30), (10, 30), [5])])
    )


@pytest.mark.parametrize("weekday", [0, 8])
def test_a_block_outside_the_week_is_invalid(weekday: int) -> None:
    """ISO weekdays are 1 to 7."""
    with pytest.raises(TermBellsInvalidError):
        validate_term(term_with([block(1, (9, 0), (10, 0), [weekday])]))


# - - - EMIS - - -


def test_the_sync_keeps_a_friday_of_its_own() -> None:
    """A different Friday survives: the period belongs to Administration."""
    emis = bells_from_class_hours(FAKE_CLASS_HOURS)
    week = block(1, (8, 30), (9, 50), [1, 2, 3, 4]).model_copy(
        update={"source": "override"}
    )
    friday = block(1, (8, 0), (8, 40), [5])

    merged = merge_emis_bells([week, friday], emis)

    assert merged is not None
    term = term_with(merged)
    assert bell_for(term, 1, 1) == (dt.time(8, 30), dt.time(9, 50))
    assert bell_for(term, 1, 5) == (dt.time(8, 0), dt.time(8, 40))
    assert bell_for(term, 2, 5) == (dt.time(10, 10), dt.time(11, 30))


def test_the_sync_does_not_bring_back_a_block_removed_from_friday() -> None:
    """Friday has fewer lessons: EMIS must not refill the emptied day."""
    emis = bells_from_class_hours(FAKE_CLASS_HOURS)
    week = emis[0].model_copy(update={"weekdays": [1, 2, 3, 4], "source": "override"})

    merged = merge_emis_bells([week, *emis[1:]], emis)

    assert merged is not None
    assert bell_for(term_with(merged), 1, 5) is None


def test_weekend_blocks_stay_and_leave_the_school_week_to_emis() -> None:
    """EMIS knows Monday to Friday only; a Saturday copy changes nothing there."""
    emis = bells_from_class_hours(FAKE_CLASS_HOURS)
    saturday = block(1, (9, 0), (10, 0), [6])

    merged = merge_emis_bells([*emis, saturday], emis)

    assert merged is None
    moved = merge_emis_bells([saturday], emis)
    assert moved is not None
    term = term_with(moved)
    assert bell_for(term, 1, 6) == (dt.time(9, 0), dt.time(10, 0))
    assert bell_for(term, 1, 1) == (dt.time(8, 30), dt.time(9, 50))


# - - - entries and lessons use the day's blocks - - -


async def test_lessons_get_the_times_of_their_own_day(env: Env) -> None:
    """Generation reads the block of the lesson's weekday."""
    term = await env.term(bells=WEEK)
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=1, period=2, subject=subject, audience=audience)
    await env.entry(term, weekday=2, period=2, subject=subject, audience=audience)

    await env.services.generate_lessons.execute(
        term_id=term.id, from_date=MONDAY, days=2
    )

    lessons = {lesson.date: lesson for lesson in await env.lessons()}
    tashkent = dt.timezone(dt.timedelta(hours=5))
    assert lessons[MONDAY].starts_at.astimezone(tashkent).time() == dt.time(10, 10)
    assert lessons[TUESDAY].starts_at.astimezone(tashkent).time() == dt.time(11, 0)


async def test_an_entry_on_a_saturday_with_blocks_makes_a_lesson(env: Env) -> None:
    """Administration opened Saturday, so the slot is accepted and generated."""
    term = await env.term(bells=WEEK)
    subject = await env.subject()
    group = await env.group()

    saved = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, weekday=6, period=1)
    )
    await env.services.generate_lessons.execute(
        term_id=term.id, from_date=FRIDAY, days=3
    )

    assert saved.weekday == 6
    assert [lesson.date for lesson in await env.lessons()] == [SATURDAY]


@pytest.mark.parametrize("weekday", [6, 7])
async def test_a_weekend_without_blocks_stays_closed(env: Env, weekday: int) -> None:
    """A day with no block at all is not a school day."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()

    with pytest.raises(EntryNotSchoolDayError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, group.id, weekday=weekday)
        )


async def test_an_entry_needs_a_block_of_its_period_on_its_day(env: Env) -> None:
    """Friday has no lesson 3, whatever the other days have."""
    term = await env.term(
        bells=[block(3, (12, 0), (13, 0), [1]), block(1, (9, 0), (10, 0), [5])]
    )
    subject = await env.subject()
    group = await env.group()

    with pytest.raises(NoBellError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, group.id, weekday=5, period=3)
        )


async def test_moving_an_entry_checks_the_new_day(env: Env) -> None:
    """A patch is validated against the blocks of the target day."""
    term = await env.term(
        bells=[block(3, (12, 0), (13, 0), [1]), block(1, (9, 0), (10, 0), [5])]
    )
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, weekday=1, period=3)
    )

    with pytest.raises(NoBellError):
        await env.services.update_entry.execute(ADMIN, saved.id, EntryPatch(weekday=5))
