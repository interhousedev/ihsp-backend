"""ACA-4, ACA-7: EMIS class hours are the bells; a change moves future lessons only."""

import datetime as dt

from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.modules.academic.domain.schedule.term import Bell, Term
from app.shared.actor import Role
from app.shared.contracts.emis import EmisAuthFailed, EmisClassHour, EmisUnavailable
from app.shared.ids import new_id
from tests.academic.schedule.env import TODAY, Env
from tests.factories import make_actor

import pytest

STUDENT = new_id()
ADMIN = make_actor(Role.ADMIN)


async def stored_term(env: Env, term: Term) -> Term:
    async with env.uow_factory() as uow:
        found = await uow.terms.get(term.id)
    assert found is not None
    return found


def shifted_hours(env: Env) -> None:
    """EMIS moves the second pair from 10:10-11:30 to 10:20-11:40."""
    env.emis.hours[1] = EmisClassHour(1, dt.time(10, 20), dt.time(11, 40))


async def test_the_bells_of_the_current_term_become_the_emis_class_hours(
    env: Env,
) -> None:
    """ACA-4: pair 0 is period 1; the bells are marked as coming from EMIS."""
    term = await env.term()

    result = await env.emis_import.sync_class_hours.execute(STUDENT)

    assert (result.status, result.term_id) == ("changed", term.id)
    bells = (await stored_term(env, term)).bells
    assert [(b.period, b.start, b.end) for b in bells] == [
        (1, dt.time(8, 30), dt.time(9, 50)),
        (2, dt.time(10, 10), dt.time(11, 30)),
        (3, dt.time(12, 10), dt.time(13, 30)),
        (4, dt.time(13, 40), dt.time(15, 0)),
        (5, dt.time(15, 10), dt.time(16, 30)),
    ]
    assert {b.source for b in bells} == {"emis"}
    assert all(b.weekdays == [1, 2, 3, 4, 5] for b in bells)
    assert env.emis.calls == [("class_hours", STUDENT)]


async def test_bells_equal_to_emis_are_not_written_again(env: Env) -> None:
    """ACA-4: only when they differ; nothing is regenerated for a no-op."""
    await env.term()
    await env.emis_import.sync_class_hours.execute(STUDENT)
    env.kicker.calls.clear()

    again = await env.emis_import.sync_class_hours.execute(STUDENT)

    assert (again.status, again.lessons_changed) == ("unchanged", 0)
    assert env.kicker.calls == []


async def test_only_the_current_term_gets_the_bells(env: Env) -> None:
    """ACA-4: "bells of the current term"; the next term keeps its own."""
    current = await env.term()
    later = await env.term(
        starts_on=dt.date(2026, 12, 26), ends_on=dt.date(2027, 5, 30), half=2
    )

    await env.emis_import.sync_class_hours.execute(STUDENT)

    assert (await stored_term(env, later)).bells == later.bells
    assert (await stored_term(env, current)).bells != current.bells


async def test_manual_bells_of_other_periods_survive_the_sync(env: Env) -> None:
    """ACA-4: Administration's sixth period is not EMIS's to remove."""
    sixth = Bell(
        period=6, start=dt.time(16, 40), end=dt.time(18, 0), weekdays=[1, 2, 3, 4, 5]
    )
    term = await env.term(bells=[sixth])

    await env.emis_import.sync_class_hours.execute(STUDENT)

    bells = (await stored_term(env, term)).bells
    assert [(b.period, b.source) for b in bells] == [
        (1, "emis"),
        (2, "emis"),
        (3, "emis"),
        (4, "emis"),
        (5, "emis"),
        (6, "manual"),
    ]


async def test_a_bell_change_moves_future_lessons_and_leaves_the_rest(
    env: Env,
) -> None:
    """ACA-7: past lessons and hand-edited lessons keep their times."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    audience = [str(group.id)]
    await env.entry(term, weekday=2, period=2, subject=subject, audience=audience)
    await env.entry(term, weekday=3, period=2, subject=subject, audience=audience)
    await env.emis_import.sync_class_hours.execute(STUDENT)
    await env.services.generate_lessons.execute(term_id=None, from_date=TODAY, days=14)
    by_date = {x.date: x for x in await env.lessons()}
    edited_day = dt.date(2026, 10, 14)  # the second Wednesday: edited by hand
    await env.services.update_lesson.execute(
        ADMIN, by_date[edited_day].id, LessonPatch(room_name="Lab")
    )
    before = {x.id: x for x in await env.lessons()}
    shifted_hours(env)

    result = await env.emis_import.sync_class_hours.execute(STUDENT)

    after = {x.id: x for x in await env.lessons()}
    assert result.status == "changed" and result.lessons_changed > 0
    untouched = [by_date[TODAY].id, by_date[edited_day].id]  # past, hand-edited
    for lesson_id in untouched:
        assert (after[lesson_id].starts_at, after[lesson_id].ends_at) == (
            before[lesson_id].starts_at,
            before[lesson_id].ends_at,
        )
    moved = [x for x in after.values() if x.id not in untouched]
    assert moved and all(
        (x.starts_at.time(), x.ends_at.time()) == (dt.time(5, 20), dt.time(6, 40))
        for x in moved
    )


async def test_a_bell_change_does_not_generate_lessons_further_ahead(env: Env) -> None:
    """ACA-7: lessons stay 14 days ahead; the sync only moves the existing ones."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=2, subject=subject, audience=[str(group.id)]
    )
    await env.services.generate_lessons.execute(term_id=None, from_date=TODAY, days=14)
    dates = [x.date for x in await env.lessons()]
    shifted_hours(env)

    await env.emis_import.sync_class_hours.execute(STUDENT)

    assert [x.date for x in await env.lessons()] == dates


async def test_lessons_generated_further_ahead_move_too(env: Env) -> None:
    """ACA-7: a longer window (seed, manual run) is followed up to its last lesson."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=2, subject=subject, audience=[str(group.id)]
    )
    await env.services.generate_lessons.execute(term_id=None, from_date=TODAY, days=40)
    shifted_hours(env)

    await env.emis_import.sync_class_hours.execute(STUDENT)

    lessons = await env.lessons()
    assert len(lessons) == 6 and all(
        x.starts_at.time() == dt.time(5, 20) for x in lessons
    )


async def test_new_lessons_use_the_emis_times(env: Env) -> None:
    """ACA-7: lessons generated after a sync start and end at EMIS times."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )
    await env.emis_import.sync_class_hours.execute(STUDENT)

    await env.services.generate_lessons.execute(term_id=None, from_date=TODAY, days=14)

    first = (await env.lessons())[0]
    assert first.starts_at == dt.datetime(2026, 10, 7, 3, 30, tzinfo=dt.UTC)
    assert first.ends_at == dt.datetime(2026, 10, 7, 4, 50, tzinfo=dt.UTC)


async def test_an_empty_answer_never_wipes_the_bells(env: Env) -> None:
    """ACA-4: EMIS answering with no pairs must not leave the term without bells."""
    term = await env.term()
    env.emis.hours.clear()

    result = await env.emis_import.sync_class_hours.execute(STUDENT)

    assert result.status == "empty"
    assert (await stored_term(env, term)).bells == term.bells


async def test_without_a_term_there_is_nothing_to_store(env: Env) -> None:
    """ACA-4: bells belong to a term."""
    result = await env.emis_import.sync_class_hours.execute(STUDENT)

    assert result.status == "no_term"


@pytest.mark.parametrize("error", [EmisUnavailable(), EmisAuthFailed()])
async def test_emis_errors_reach_the_caller_and_change_nothing(
    env: Env, error: Exception
) -> None:
    """ID-7: the caller decides (task retry, or try another student)."""
    term = await env.term()
    env.emis.hours_error = error

    with pytest.raises(type(error)):
        await env.emis_import.sync_class_hours.execute(STUDENT)

    assert (await stored_term(env, term)).bells == term.bells


async def test_a_second_sync_with_the_same_hours_keeps_the_stored_bells(
    env: Env,
) -> None:
    """ACA-4: a second sync with the same hours keeps the stored bells identical."""
    term = await env.term()
    await env.emis_import.sync_class_hours.execute(STUDENT)
    first = (await stored_term(env, term)).bells

    await env.emis_import.sync_class_hours.execute(STUDENT)

    assert (await stored_term(env, term)).bells == first
