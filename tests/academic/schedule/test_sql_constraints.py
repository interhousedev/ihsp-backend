"""What only PostgreSQL enforces: exclusion constraints, savepoints, marks."""

import datetime as dt
from uuid import UUID

from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.academic.domain.schedule.errors import TermOverlapError
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.term import Term
from app.shared.actor import Role
from app.shared.base_error import ConflictError
from app.shared.ids import new_id
from tests.academic.schedule.env import TODAY, Env
from tests.factories import make_actor

import pytest

NINE = dt.datetime(2026, 10, 14, 4, 0, tzinfo=dt.UTC)


def lesson_at(
    term_id: UUID,
    subject_id: UUID,
    audience: list[str],
    *,
    start: dt.datetime,
    teacher: UUID | None = None,
    room: UUID | None = None,
) -> Lesson:
    """A lesson for 45 minutes from `start`."""
    return Lesson(
        id=new_id(),
        term_id=term_id,
        date=start.date(),
        period=1,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=45),
        subject_id=subject_id,
        teacher_id=teacher,
        room_id=room,
        audience=audience,
    )


async def test_the_database_refuses_a_teacher_in_two_lessons_at_once(
    sql_env: Env,
) -> None:
    """ACA-8: the exclusion constraint maps to ConflictError with a teacher conflict."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    async with env.uow_factory() as uow:
        await uow.lessons.add(
            lesson_at(
                term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
            )
        )
        with pytest.raises(ConflictError) as caught:
            await uow.lessons.add(
                lesson_at(
                    term.id,
                    subject.id,
                    [str(group.id)],
                    start=NINE + dt.timedelta(minutes=30),
                    teacher=teacher.id,
                )
            )

    assert caught.value.params["conflicts"][0]["kind"] == "teacher"


async def test_the_database_refuses_a_room_used_twice_at_once(sql_env: Env) -> None:
    """ACA-8: the same for rooms."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    room = await env.room("102")
    async with env.uow_factory() as uow:
        await uow.lessons.add(
            lesson_at(term.id, subject.id, [str(group.id)], start=NINE, room=room.id)
        )
        with pytest.raises(ConflictError) as caught:
            await uow.lessons.add(
                lesson_at(
                    term.id, subject.id, [str(group.id)], start=NINE, room=room.id
                )
            )

    assert caught.value.params["conflicts"][0]["kind"] == "room"


async def test_a_cancelled_lesson_does_not_block_its_teacher(sql_env: Env) -> None:
    """ACA-8: the exclusion constraint only covers scheduled lessons."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    cancelled = lesson_at(
        term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
    )
    cancelled.status = "cancelled"
    async with env.uow_factory() as uow:
        await uow.lessons.add(cancelled)
        await uow.lessons.add(
            lesson_at(
                term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
            )
        )
        await uow.commit()


async def test_try_add_reports_a_clash_and_the_transaction_stays_usable(
    sql_env: Env,
) -> None:
    """UF-SYS-05: one clashing lesson must not abort the whole generation."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    async with env.uow_factory() as uow:
        assert await uow.lessons.try_add(
            lesson_at(
                term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
            )
        )
        assert not await uow.lessons.try_add(
            lesson_at(
                term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
            )
        )
        assert await uow.lessons.try_add(
            lesson_at(
                term.id,
                subject.id,
                [str(group.id)],
                start=NINE + dt.timedelta(hours=2),
                teacher=teacher.id,
            )
        )
        await uow.commit()

    assert len(await env.lessons()) == 2


async def test_try_save_reports_a_clash_and_keeps_the_stored_lesson(
    sql_env: Env,
) -> None:
    """UF-SYS-05: an update that would clash is skipped."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    first = lesson_at(
        term.id, subject.id, [str(group.id)], start=NINE, teacher=teacher.id
    )
    second = lesson_at(
        term.id,
        subject.id,
        [str(group.id)],
        start=NINE + dt.timedelta(hours=2),
        teacher=teacher.id,
    )
    async with env.uow_factory() as uow:
        await uow.lessons.add(first)
        await uow.lessons.add(second)
        second.starts_at, second.ends_at = first.starts_at, first.ends_at
        assert not await uow.lessons.try_save(second)
        await uow.commit()

    stored = {x.id: x for x in await env.lessons()}
    assert stored[second.id].starts_at == NINE + dt.timedelta(hours=2)


async def test_the_database_refuses_overlapping_terms_even_without_the_use_case_check(
    sql_env: Env,
) -> None:
    """ACA-4: the exclusion constraint on the date range maps to TermOverlapError."""
    env = sql_env
    await env.term()
    second = Term(
        id=new_id(),
        academic_year="2027-2028",
        half=1,
        starts_on=dt.date(2026, 12, 1),
        ends_on=dt.date(2027, 1, 31),
    )
    async with env.uow_factory() as uow:
        with pytest.raises(TermOverlapError):
            await uow.terms.add(second)


async def test_a_lesson_with_a_mark_is_cancelled_not_deleted(sql_env: Env) -> None:
    """ACA-7: lessons with marks are never deleted."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    pupil = await env.student(group)
    audience = [str(group.id)]
    entry = await env.entry(
        term, weekday=1, period=1, subject=subject, audience=audience
    )
    marked = await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=audience,
        entry=entry,
    )
    empty = await env.lesson(
        term,
        day=dt.date(2026, 10, 19),
        period=1,
        subject=subject,
        audience=audience,
        entry=entry,
    )
    await env.give_mark(marked.id, pupil, subject)

    await env.services.delete_entry.execute(entry.id)

    lessons = {x.id: x for x in await env.lessons()}
    assert lessons[marked.id].status == "cancelled"
    assert empty.id not in lessons


async def test_generation_cancels_a_lesson_with_a_topic_instead_of_deleting_it(
    sql_env: Env,
) -> None:
    """ACA-7: content such as a topic also protects a lesson from deletion."""
    env = sql_env
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    entry = await env.entry(
        term, weekday=1, period=1, subject=subject, audience=audience, parity="even"
    )
    stale = await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=audience,
        entry=entry,
        starts_at=dt.datetime(2026, 10, 12, 3, 30, tzinfo=dt.UTC),
    )
    await env.services.update_lesson.execute(
        make_actor(Role.ADMIN), stale.id, LessonPatch(topic="Limits")
    )

    await env.services.generate_lessons.execute(from_date=TODAY, days=14)

    lessons = {x.id: x for x in await env.lessons()}
    assert (
        lessons[stale.id].status == "cancelled" and lessons[stale.id].topic == "Limits"
    )
