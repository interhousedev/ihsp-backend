"""ACA-5, ACA-7: what EMIS leaves on entries and lessons, and who may ask for it."""

import datetime as dt

from app.modules.academic.application.schedule.entry_builder import EntryInput
from app.modules.academic.application.schedule.update_entry import EntryPatch
from app.modules.academic.application.schedule.update_lesson import LessonPatch
from app.shared.actor import Role
from app.shared.lesson_kind import topic_source_of
from tests.academic.schedule.builders import entry_input
from tests.academic.schedule.env import Env
from tests.factories import make_actor

import pytest

ADMIN = make_actor(Role.ADMIN)
D7, D14, D21 = dt.date(2026, 10, 7), dt.date(2026, 10, 14), dt.date(2026, 10, 21)


@pytest.mark.parametrize(
    ("topic", "emis_topic", "source"),
    [
        (None, None, None),
        (None, "From EMIS", None),
        ("From EMIS", "From EMIS", "emis"),
        ("Our own", "From EMIS", "manual"),
        ("Our own", None, "manual"),
    ],
)
def test_a_topic_is_labelled_by_who_wrote_it(
    topic: str | None, emis_topic: str | None, source: str | None
) -> None:
    """The topic EMIS sent is a hint the UI can label; a written one is not."""
    assert topic_source_of(topic, emis_topic) == source


async def test_lessons_show_their_kind_and_where_the_topic_came_from(env: Env) -> None:
    """ACA-7: LessonRef carries kind and topic_source for every view."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    student = await env.student(group)
    audience = [str(group.id)]
    await env.lesson(
        term,
        day=D7,
        period=1,
        subject=subject,
        audience=audience,
        kind="midterm",
        topic="From EMIS",
        emis_topic="From EMIS",
    )
    await env.lesson(
        term,
        day=D14,
        period=1,
        subject=subject,
        audience=audience,
        topic="Written",
        emis_topic="From EMIS",
    )

    refs = await env.services.queries.lessons_for_student(student.id, D7, D14)

    assert [(r.kind, r.topic, r.topic_source) for r in refs] == [
        ("midterm", "From EMIS", "emis"),
        ("other", "Written", "manual"),
    ]


async def test_control_lessons_of_the_groups_are_offered_as_suggestions(
    env: Env,
) -> None:
    """EMIS controls: scheduled midterms and finals of the asked groups and dates."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group("2TN2")
    other = await env.group("1TN1")
    keys = [str(group.id), f"{group.id}:1"]
    midterm = await env.lesson(
        term, day=D7, period=1, subject=subject, audience=keys, kind="midterm"
    )
    final = await env.lesson(
        term, day=D21, period=2, subject=subject, audience=[keys[1]], kind="final"
    )
    await env.lesson(term, day=D7, period=2, subject=subject, audience=keys)
    await env.lesson(
        term, day=D7, period=3, subject=subject, audience=keys, kind="practice"
    )
    await env.lesson(
        term, day=D7, period=1, subject=subject, audience=[str(other.id)], kind="final"
    )
    cancelled = await env.lesson(
        term, day=D14, period=1, subject=subject, audience=keys, kind="midterm"
    )
    await env.services.update_lesson.execute(
        ADMIN, cancelled.id, LessonPatch(status="cancelled")
    )

    found = await env.services.queries.emis_control_lessons([group.id], D7, D21)
    narrower = await env.services.queries.emis_control_lessons([group.id], D7, D14)
    nobody = await env.services.queries.emis_control_lessons([], D7, D21)

    assert [(r.id, r.kind, r.date) for r in found] == [
        (midterm.id, "midterm", D7),
        (final.id, "final", D21),
    ]
    assert found[0].subject_name == "Математика"
    assert found[1].audience == (keys[1],)
    assert [r.id for r in narrower] == [midterm.id]
    assert nobody == []


async def test_editing_an_emis_entry_makes_it_a_hand_made_one(env: Env) -> None:
    """ACA-1: EMIS keeps its entries equal to EMIS; an edited one is the admin's."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    entry = await env.entry(
        term,
        weekday=2,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        source="emis",
    )

    changed = await env.services.update_entry.execute(
        ADMIN, entry.id, EntryPatch(week_parity="odd")
    )

    assert (changed.source, changed.week_parity) == ("manual", "odd")
    async with env.uow_factory() as uow:
        stored = await uow.entries.get(entry.id)
    assert stored is not None and stored.source == "manual"


async def test_an_entry_reports_where_it_came_from(env: Env) -> None:
    """ACA-1: the admin timetable shows the source of each entry."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    await env.entry(
        term,
        weekday=2,
        period=1,
        subject=subject,
        audience=[str(group.id)],
        source="emis",
    )
    await env.entry(
        term, weekday=3, period=1, subject=subject, audience=[str(group.id)]
    )

    listed = await env.services.list_entries.execute(ADMIN, term_id=term.id)

    assert [(e.weekday, e.source) for e in listed] == [(2, "emis"), (3, "manual")]


async def test_a_conflict_says_in_which_weeks_the_other_entry_runs(env: Env) -> None:
    """ACA-8: an odd-week entry blocks an every-week one, and the check shows why."""
    term = await env.term()
    subject = await env.subject()
    group = await env.group()
    teacher = env.teacher()
    await env.services.create_entry.execute(
        ADMIN,
        EntryInput(
            term_id=term.id,
            weekday=1,
            period=1,
            week_parity="odd",
            subject_id=subject.id,
            teacher_id=teacher.id,
            room_name=None,
            audience=[(group.id, None)],
            valid_from=dt.date(2026, 9, 1),
            valid_to=None,
        ),
    )
    other_group = await env.group("1TN1")

    overlapping = await env.services.check_entry.execute(
        entry_input(term.id, subject.id, other_group.id, teacher_id=teacher.id)
    )
    even_weeks = await env.services.check_entry.execute(
        entry_input(
            term.id, subject.id, other_group.id, teacher_id=teacher.id, parity="even"
        )
    )

    assert [(c.kind, c.week_parity) for c in overlapping] == [("teacher", "odd")]
    assert even_weeks == []


def test_emis_lesson_plans_are_imported_unless_the_setting_says_no() -> None:
    """EMIS__IMPORT_TOPICS is on by default and documented in the env sample."""
    from pathlib import Path

    from app.settings import EmisSettings

    sample = (Path(__file__).parents[3] / "materials" / ".env.sample").read_text()

    assert EmisSettings().import_topics is True
    assert "IHSP_EMIS__IMPORT_TOPICS=true" in sample
