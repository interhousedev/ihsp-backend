"""Lesson generation from the timetable (UF-SYS-05, ACA-7)."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.update_entry import EntryPatch
from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.academic.domain.schedule.term import MovedDay
from app.shared.actor import Role
from tests.academic.schedule.builders import entry_input
from tests.academic.schedule.env import TODAY, Env
from tests.factories import make_actor

ADMIN = make_actor(Role.ADMIN)


async def generate(
    env: Env,
    *,
    from_date: dt.date | None = TODAY,
    days: int = 14,
    term_id: UUID | None = None,
) -> int:
    """Run the generation use case."""
    return await env.services.generate_lessons.execute(
        term_id=term_id, from_date=from_date, days=days
    )


async def test_lessons_are_created_for_14_days_and_skip_holidays(env: Env) -> None:
    """UF-SYS-05: 14 days ahead; ACA-7: nothing on non-study days."""
    term = await env.term(non_study_days=[dt.date(2026, 10, 12)])
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=1, period=1, subject=subject, audience=audience)
    await env.entry(term, weekday=3, period=2, subject=subject, audience=audience)

    changed = await generate(env)

    lessons = await env.lessons()
    assert [(x.date, x.period) for x in lessons] == [
        (dt.date(2026, 10, 7), 2),
        (dt.date(2026, 10, 14), 2),
        (dt.date(2026, 10, 19), 1),
    ]
    assert changed == 3
    first = lessons[0]
    assert first.starts_at == dt.datetime(2026, 10, 7, 4, 25, tzinfo=dt.UTC)
    assert first.ends_at == dt.datetime(2026, 10, 7, 5, 10, tzinfo=dt.UTC)
    assert first.status == "scheduled" and first.audience == audience
    assert first.origin_date == first.date and first.timetable_entry_id is not None


async def test_generation_asks_classwork_to_recompute_due_dates(env: Env) -> None:
    """UF-SYS-05 step 4: homework due dates follow the new lessons."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )

    await generate(env)

    ids = {str(x.id) for x in await env.lessons()}
    calls = [
        kw for name, kw in env.kicker.calls if name == "academic.recompute_due_dates"
    ]
    assert calls and set(calls[0]["lesson_ids"]) == ids


async def test_running_twice_creates_nothing_new(env: Env) -> None:
    """UF-SYS-05: lessons are identified by entry and original date."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )
    await generate(env)
    before = {x.id for x in await env.lessons()}

    again = await generate(env)

    assert again == 0
    assert {x.id for x in await env.lessons()} == before


async def test_a_moved_friday_uses_the_timetable_it_follows(env: Env) -> None:
    """ACA-4: Friday 16.10 follows Monday, so Monday's lessons run on it."""
    term = await env.term(
        moved_days=[MovedDay(date=dt.date(2026, 10, 16), follows_weekday=1)]
    )
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=1, period=1, subject=subject, audience=[str(group.id)]
    )

    await generate(env)

    assert [x.date for x in await env.lessons()] == [
        dt.date(2026, 10, 12),
        dt.date(2026, 10, 16),
        dt.date(2026, 10, 19),
    ]


async def test_entries_without_a_bell_are_skipped_without_failing(env: Env) -> None:
    """ACA-7: an entry whose period has no bell makes no lessons."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=3, period=9, subject=subject, audience=audience)
    await env.entry(term, weekday=3, period=1, subject=subject, audience=audience)

    await generate(env)

    assert [x.period for x in await env.lessons()] == [1, 1]


async def test_generation_can_be_limited_to_one_term_and_a_start_date(env: Env) -> None:
    """Task academic.generate_lessons(term_id, from_date, days)."""
    first = await env.term()
    second = await env.term(
        starts_on=dt.date(2026, 12, 26), ends_on=dt.date(2027, 5, 30), half=2
    )
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(first, weekday=3, period=1, subject=subject, audience=audience)
    await env.entry(second, weekday=3, period=1, subject=subject, audience=audience)

    await generate(env, from_date=dt.date(2026, 12, 21), days=21, term_id=second.id)

    lessons = await env.lessons()
    assert [x.term_id for x in lessons] == [second.id, second.id]
    assert [x.date for x in lessons] == [dt.date(2026, 12, 30), dt.date(2027, 1, 6)]


async def test_a_term_that_does_not_cover_the_window_makes_no_lessons(env: Env) -> None:
    """UF-SYS-05: only terms overlapping the window are expanded."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )

    assert await generate(env, from_date=dt.date(2027, 3, 1)) == 0


async def test_regenerating_after_a_room_change_updates_future_lessons_only(
    env: Env,
) -> None:
    """ACA-7: a timetable change reaches future lessons, not past or manual ones."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN,
        entry_input(term.id, subject.id, group.id, weekday=2, room_name="102"),
    )
    await generate(
        env, from_date=dt.date(2026, 10, 5), days=21
    )  # Tuesdays 6th (past), 13th, 20th
    by_date = {x.date: x for x in await env.lessons()}
    assert set(by_date) == {
        dt.date(2026, 10, 6),
        dt.date(2026, 10, 13),
        dt.date(2026, 10, 20),
    }
    await env.services.update_lesson.execute(
        ADMIN, by_date[dt.date(2026, 10, 20)].id, LessonPatch(room_name="Lab")
    )

    await env.services.update_entry.execute(
        ADMIN, saved.id, EntryPatch(room_name="103")
    )
    await generate(env, from_date=dt.date(2026, 10, 5), days=21)

    async with env.uow_factory() as uow:
        rooms = {r.name: r.id for r in await uow.rooms.list_all()}
    after = {x.date: x for x in await env.lessons()}
    assert after[dt.date(2026, 10, 6)].room_id == rooms["102"]  # already started
    assert after[dt.date(2026, 10, 13)].room_id == rooms["103"]  # follows the timetable
    assert after[dt.date(2026, 10, 20)].room_id == rooms["Lab"]  # changed by hand
    assert after[dt.date(2026, 10, 20)].is_overridden


async def test_a_parity_change_deletes_empty_lessons_and_cancels_those_with_homework(
    env: Env,
) -> None:
    """ACA-7: lessons an entry no longer makes: deleted, or cancelled if used."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    saved = await env.services.create_entry.execute(
        ADMIN, entry_input(term.id, subject.id, group.id, weekday=1)
    )
    await generate(env, days=21)  # Mondays 12th (odd week), 19th (even), 26th (odd)
    by_date = {x.date: x for x in await env.lessons()}
    await env.give_homework(by_date[dt.date(2026, 10, 26)].id)

    await env.services.update_entry.execute(
        ADMIN, saved.id, EntryPatch(week_parity="even")
    )
    await generate(env, days=21)

    after = {x.date: x for x in await env.lessons()}
    assert dt.date(2026, 10, 12) not in after  # empty: deleted
    assert after[dt.date(2026, 10, 26)].status == "cancelled"  # has homework
    assert after[dt.date(2026, 10, 19)].status == "scheduled"


async def test_a_busy_teacher_blocks_only_the_lesson_that_clashes(env: Env) -> None:
    """ACA-8: an extra lesson that took the teacher's slot is not overwritten."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN1")
    other = await env.group("2TN2")
    teacher = env.teacher()
    await env.entry(
        term,
        weekday=1,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=[str(other.id)],
        teacher=teacher,
        starts_at=dt.datetime(2026, 10, 12, 3, 30, tzinfo=dt.UTC),
        overridden=True,
    )

    changed = await generate(env)

    generated = [x for x in await env.lessons() if x.timetable_entry_id is not None]
    assert [x.date for x in generated] == [dt.date(2026, 10, 19)]
    assert changed == 1


async def test_entries_without_a_teacher_make_teacher_needed_lessons(env: Env) -> None:
    """ACA-7: an entry without a teacher generates 'teacher needed' lessons."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )

    await generate(env)

    assert {x.teacher_id for x in await env.lessons()} == {None}
