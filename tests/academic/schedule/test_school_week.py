"""The lyceum studies Monday to Friday; weekend rows from before are never read."""

import datetime as dt
import json
from typing import cast
from uuid import UUID

from app.modules.academic.application.classwork.ports.lesson_reader import LessonReader
from app.modules.academic.application.classwork.student_context import StudyDays
from app.modules.academic.application.public_schedule import ScheduleQueriesImpl
from app.modules.academic.application.schedule.update_entry import EntryPatch
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.errors import (
    EntryInvalidError,
    EntryNotSchoolDayError,
    TermMovedDayInvalidError,
)
from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.modules.academic.domain.schedule.term import Bell, MovedDay
from app.modules.academic.domain.schedule.timetable_entry import (
    TimetableEntry,
    validate_entry,
)
from app.modules.academic.infrastructure.classwork.lesson_reader import SqlLessonReader
from app.shared.actor import Role
from app.shared.ids import new_id
from app.shared.paths import LOCALES_DIR
from tests.academic.schedule.builders import entry_input
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)

THURSDAY = dt.date(2026, 10, 8)
FRIDAY = dt.date(2026, 10, 9)
SATURDAY = dt.date(2026, 10, 10)
SUNDAY = dt.date(2026, 10, 11)
MONDAY = dt.date(2026, 10, 12)
LOCALE = "ru"


def make_entry(weekday: int, **kwargs: object) -> TimetableEntry:
    """A valid period-1 entry of one group on the weekday."""
    fields: dict[str, object] = {
        "id": new_id(),
        "term_id": new_id(),
        "weekday": weekday,
        "period": 1,
        "week_parity": "every",
        "subject_id": new_id(),
        "teacher_id": None,
        "room_id": None,
        "audience": [audience_keys.key(new_id(), None)],
        "valid_from": dt.date(2026, 9, 1),
        "valid_to": None,
    }
    fields.update(kwargs)
    return TimetableEntry(**fields)  # type: ignore[arg-type]


class NoGeneratedLessons:
    """The classwork reader of a student whose lessons are not generated yet."""

    async def next_study_day(self, keys: list[str], after: dt.date) -> dt.date | None:
        """Nothing is generated, so the schedule has to project the days."""
        return None


# - - - the rule of one entry - - -


def test_the_school_week_is_monday_to_friday() -> None:
    """ISO weekdays 1-5; Saturday (6) and Sunday (7) are not school days."""
    assert SCHOOL_DAYS == (1, 2, 3, 4, 5)


@pytest.mark.parametrize("weekday", [1, 2, 3, 4, 5])
def test_an_entry_on_a_school_day_is_valid(weekday: int) -> None:
    """ACA-5: Monday to Friday are accepted."""
    validate_entry(make_entry(weekday))


def test_an_entry_on_a_saturday_is_rejected_as_not_a_school_day() -> None:
    """Lessons are held Monday to Friday; a Saturday slot is not allowed."""
    with pytest.raises(EntryNotSchoolDayError) as error:
        validate_entry(make_entry(6))

    assert error.value.code == "academic/entry-not-school-day"
    assert error.value.message_key == "academic-entry-not-school-day"
    assert error.value.status == 422


@pytest.mark.parametrize("weekday", [0, 7, 8])
def test_any_other_weekday_stays_an_invalid_slot(weekday: int) -> None:
    """Out-of-range weekdays keep the general error."""
    with pytest.raises(EntryInvalidError) as error:
        validate_entry(make_entry(weekday))

    assert not isinstance(error.value, EntryNotSchoolDayError)
    assert error.value.params == {"reason": "slot"}


# - - - the admin timetable - - -


async def test_creating_an_entry_on_a_saturday_is_rejected(env: Env) -> None:
    """ACA-5: the admin form cannot make a Saturday slot."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()

    with pytest.raises(EntryNotSchoolDayError):
        await env.services.create_entry.execute(
            ADMIN, entry_input(term.id, subject.id, group.id, weekday=6)
        )

    assert env.kicker.calls == []  # nothing was saved, so nothing is regenerated


async def test_updating_an_entry_onto_a_saturday_is_rejected(env: Env) -> None:
    """ACA-5: moving a slot to Saturday fails and the slot stays where it was."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, weekday=5)
    )

    with pytest.raises(EntryNotSchoolDayError):
        await env.services.update_entry.execute(ADMIN, saved.id, EntryPatch(weekday=6))

    listed = await env.services.list_entries.execute(ADMIN)
    assert [(e.id, e.weekday) for e in listed] == [(saved.id, 5)]


async def test_saturday_entries_from_before_are_neither_listed_nor_copied(
    env: Env,
) -> None:
    """Old rows stay in the table, but the grid and the copy do not see them."""
    term = await env.term()
    following = await env.term(
        starts_on=dt.date(2027, 1, 11),
        ends_on=dt.date(2027, 5, 30),
        academic_year="2026-2027",
        half=2,
    )
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=1, period=1, subject=subject, audience=audience)
    await env.entry(term, weekday=6, period=1, subject=subject, audience=audience)

    listed = await env.services.list_entries.execute(ADMIN)
    created = await env.services.copy_timetable.execute(term.id, following.id)

    assert [e.weekday for e in listed] == [1]
    assert created == 1
    copied = await env.services.list_entries.execute(ADMIN, term_id=following.id)
    assert [e.weekday for e in copied] == [1]


# - - - generation and reads skip Saturday - - -


async def test_nothing_is_generated_for_a_saturday_entry_from_before(env: Env) -> None:
    """Weekday 6 may still be stored on an old entry; no lessons come from it."""
    bells = [
        Bell(period=1, start=dt.time(8, 30), end=dt.time(9, 15), weekdays=[1, 2, 3])
    ]
    term = await env.term(bells=bells)
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=6, period=1, subject=subject, audience=audience)
    await env.entry(term, weekday=1, period=1, subject=subject, audience=audience)

    await env.services.generate_lessons.execute(
        term_id=term.id, from_date=THURSDAY, days=14
    )

    assert [x.date for x in await env.lessons()] == [MONDAY, MONDAY + dt.timedelta(7)]


async def test_regenerating_never_deletes_a_saturday_lesson_from_before(
    env: Env,
) -> None:
    """Old Saturday lessons stay in the table: generation does not touch them."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    old_entry = await env.entry(
        term, weekday=6, period=1, subject=subject, audience=audience
    )
    saturday = await env.lesson(
        term,
        day=SATURDAY,
        period=1,
        subject=subject,
        audience=audience,
        entry=old_entry,
    )

    await env.services.generate_lessons.execute(
        term_id=term.id, from_date=THURSDAY, days=14
    )

    assert [x.id for x in await env.lessons()] == [saturday.id]
    assert [x.status for x in await env.lessons()] == ["scheduled"]


async def test_lessons_dated_on_a_saturday_are_not_read_but_a_sunday_is(
    env: Env,
) -> None:
    """Saturday lessons from before stay hidden; a moved Sunday is a real day."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    teacher = env.teacher()
    audience = [str(group.id)]
    days = {
        name: await env.lesson(
            term, day=day, period=1, subject=subject, audience=audience, teacher=teacher
        )
        for name, day in (("fri", FRIDAY), ("sat", SATURDAY), ("sun", SUNDAY))
    }

    mine = await env.reader.lessons_for_student(pupil.id, FRIDAY, MONDAY, LOCALE)
    taught = await env.reader.lessons_for_teacher(teacher.id, FRIDAY, MONDAY, LOCALE)
    single = await env.reader.lesson_view(days["sat"].id, LOCALE)
    kept = await env.reader.lesson_view(days["sun"].id, LOCALE)

    expected = [days["fri"].id, days["sun"].id]
    assert [v.ref.id for v in mine] == expected
    assert [v.ref.id for v in taught] == expected
    assert single is None
    assert kept is not None
    assert {x.id for x in await env.lessons()} == {x.id for x in days.values()}


# - - - the next study day - - -


async def next_study_day(
    env: Env, pupil: UUID, group_id: UUID, after: dt.date
) -> object:
    """StudyDays over the real schedule queries when no lesson is generated yet."""
    days = StudyDays(ScheduleQueriesImpl(env.reader))
    keys = audience_keys.student_keys(group_id, None)
    reader = cast(LessonReader, NoGeneratedLessons())
    return await days.next_after(reader, pupil, keys, after)


async def test_the_next_study_day_after_friday_is_monday(env: Env) -> None:
    """The dashboard card looks past the weekend: a Saturday entry changes nothing."""
    bells = [
        Bell(
            period=1,
            start=dt.time(8, 30),
            end=dt.time(9, 15),
            weekdays=[1, 2, 3, 4, 5, 6],
        )
    ]
    term = await env.term(bells=bells)
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    audience = [str(group.id)]
    await env.entry(term, weekday=5, period=1, subject=subject, audience=audience)
    await env.entry(term, weekday=6, period=1, subject=subject, audience=audience)
    await env.entry(term, weekday=1, period=1, subject=subject, audience=audience)

    assert await next_study_day(env, pupil.id, group.id, FRIDAY) == MONDAY
    assert await next_study_day(env, pupil.id, group.id, THURSDAY) == FRIDAY
    assert await next_study_day(env, pupil.id, group.id, SATURDAY) == MONDAY


async def test_a_sunday_lesson_from_before_is_not_the_next_school_day(env: Env) -> None:
    """The next school day after Friday is Monday, even with a stored Sunday lesson."""
    if env.maker is None:
        pytest.skip("the classwork lesson reader runs on a session")
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.lesson(term, day=SUNDAY, period=1, subject=subject, audience=audience)
    await env.lesson(term, day=MONDAY, period=1, subject=subject, audience=audience)

    async with env.maker() as session:
        found = await SqlLessonReader(session).next_study_day(
            audience_keys.student_keys(group.id, None), FRIDAY
        )

    assert found == MONDAY


async def test_a_moved_sunday_rule_does_not_make_sunday_the_next_study_day(
    env: Env,
) -> None:
    """Sunday is not a school day: a moved-day rule for it changes nothing."""
    term = await env.term(
        moved_days=[MovedDay(date=SUNDAY, follows_weekday=1)],
    )
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    await env.entry(
        term, weekday=1, period=1, subject=subject, audience=[str(group.id)]
    )

    assert await next_study_day(env, pupil.id, group.id, FRIDAY) == MONDAY


# - - - messages - - -


@pytest.mark.parametrize("lang", ["en", "ru", "uz"])
def test_the_school_week_messages_exist_in_every_language(lang: str) -> None:
    """CODESTYLE: i18n keys added for all three languages."""
    path = LOCALES_DIR / lang / "academic_schedule.json"
    messages: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))

    assert EntryNotSchoolDayError.message_key in messages
    assert TermMovedDayInvalidError.message_key in messages
    assert messages[EntryNotSchoolDayError.message_key]
