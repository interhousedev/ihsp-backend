"""A deactivated teacher leaves the schedule (ACA-7, ADM-4)."""

import datetime as dt

from tests.academic.schedule.env import Env


async def test_the_teacher_is_cleared_from_entries_and_future_lessons(env: Env) -> None:
    """ACA-7: lessons become 'teacher needed'; past lessons keep their teacher."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    leaving = env.teacher()
    staying = env.teacher("Dilorom", "Ismoilova")
    audience = [str(group.id)]
    entry = await env.entry(
        term, weekday=1, period=1, subject=subject, audience=audience, teacher=leaving
    )
    other_entry = await env.entry(
        term, weekday=2, period=1, subject=subject, audience=audience, teacher=staying
    )
    past = await env.lesson(
        term,
        day=dt.date(2026, 10, 5),
        period=1,
        subject=subject,
        audience=audience,
        teacher=leaving,
        entry=entry,
    )
    future = await env.lesson(
        term,
        day=dt.date(2026, 10, 12),
        period=1,
        subject=subject,
        audience=audience,
        teacher=leaving,
        entry=entry,
    )
    kept = await env.lesson(
        term,
        day=dt.date(2026, 10, 13),
        period=1,
        subject=subject,
        audience=audience,
        teacher=staying,
        entry=other_entry,
    )

    cleared = await env.services.teacher_deactivated.execute(leaving.id)

    assert cleared == (1, 1)
    lessons = {x.id: x for x in await env.lessons()}
    assert lessons[past.id].teacher_id == leaving.id
    assert lessons[future.id].teacher_id is None
    assert lessons[kept.id].teacher_id == staying.id
    async with env.uow_factory() as uow:
        cleared_entry = await uow.entries.get(entry.id)
        kept_entry = await uow.entries.get(other_entry.id)
    assert cleared_entry is not None and cleared_entry.teacher_id is None
    assert kept_entry is not None and kept_entry.teacher_id == staying.id
    [audit] = env.audits
    assert (audit.type, audit.user_id) == ("teacher.unassigned", leaving.id)
    assert audit.metadata == {"entries": 1, "lessons": 1}


async def test_a_teacher_without_schedule_leaves_no_audit_event(env: Env) -> None:
    """ACA-7: nothing to clear, nothing to record."""
    teacher = env.teacher()

    cleared = await env.services.teacher_deactivated.execute(teacher.id)

    assert cleared == (0, 0)
    assert env.audits == []


async def test_generated_lessons_stay_teacher_needed_after_regeneration(
    env: Env,
) -> None:
    """ACA-7: lessons generated later also have no teacher."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    await env.entry(
        term,
        weekday=3,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        teacher=teacher,
    )
    await env.services.teacher_deactivated.execute(teacher.id)

    await env.services.generate_lessons.execute(from_date=dt.date(2026, 10, 6), days=14)

    assert {x.teacher_id for x in await env.lessons()} == {None}
