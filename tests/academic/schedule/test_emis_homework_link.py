"""EMIS-only homework (a homework file, no teacher text) counts as homework."""

import datetime as dt
from typing import Any, cast
from uuid import UUID

from app.modules.academic.application.schedule.emis_lessons import (
    LessonReconciler,
    LessonTally,
)
from app.modules.academic.application.schedule.emis_subjects import SubjectResolver
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.marks.read_models import LessonRow as MarksLessonRow
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.infrastructure.orm import Lesson as LessonOrm
from app.modules.academic.infrastructure.schedule.mappers import (
    lesson_apply,
    lesson_to_entity,
)
from app.modules.academic.infrastructure.schedule.repositories.lesson_repository import (  # noqa: E501
    has_content_clause,
)
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.emis import EmisTopic
from app.shared.ids import new_id
from tests.academic.schedule.builders import make_term
from tests.academic.schedule.emis_builders import day, klass
from tests.fakes.academic.schedule.store import ScheduleStore
from tests.fakes.academic.schedule.uow import FakeScheduleUnitOfWork

from sqlalchemy.dialects import postgresql

HW_URL = "https://emis.example/hw.pdf"
NOW = dt.datetime(2026, 10, 1, 8, tzinfo=dt.UTC)


def _lesson(term: Term, group_id: UUID, teacher_id: UUID | None) -> Lesson:
    date = day(0, 1)
    starts = dt.datetime.combine(date, dt.time(8, 30), tzinfo=dt.UTC)
    return Lesson(
        id=new_id(),
        term_id=term.id,
        date=date,
        period=1,
        starts_at=starts,
        ends_at=starts + dt.timedelta(minutes=80),
        subject_id=new_id(),
        teacher_id=teacher_id,
        room_id=None,
        audience=[audience_keys.key(group_id, None)],
    )


async def _sync(
    store: ScheduleStore, term: Term, group_id: UUID, topic: EmisTopic | None
) -> LessonTally:
    uow = FakeScheduleUnitOfWork(store)
    async with uow:
        tally = await LessonReconciler(
            cast(Any, uow),
            term=term,
            group_id=group_id,
            teachers=cast(Any, None),  # the lesson exists: nobody is resolved
            subjects=SubjectResolver(cast(Any, uow)),
            emis_entry_ids=(),
            now=NOW,
            today=NOW.date(),
            import_topics=True,
        ).run([klass(0, 1, topic=topic)], [None], (day(0, 1), day(0, 5)))
        await uow.commit()
    return tally


async def test_sync_stores_the_homework_file_and_applies_the_teacher_default() -> None:
    """The first EMIS homework file sets the switch from the teacher's default."""
    store = ScheduleStore()
    term = make_term()
    store.terms[term.id] = term
    group_id, teacher_id = new_id(), new_id()
    lesson = _lesson(term, group_id, teacher_id)
    store.lessons[lesson.id] = lesson
    store.homework_accept_defaults[teacher_id] = True
    topic = EmisTopic("Fractions", description="Pages 10-12", homework_file_url=HW_URL)

    tally = await _sync(store, term, group_id, topic)

    saved = store.lessons[lesson.id]
    assert (saved.emis_homework_url, saved.emis_topic_description) == (
        HW_URL,
        "Pages 10-12",
    )
    assert tally.new_homework == [lesson.id]
    assert lesson.id in tally.changed  # the automatic due date follows
    assert store.homework_accept == {lesson.id: True}


async def test_a_second_sync_does_not_reapply_the_default() -> None:
    """Only the appearance of the file applies the default; a teacher's toggle stays."""
    store = ScheduleStore()
    term = make_term()
    store.terms[term.id] = term
    group_id, teacher_id = new_id(), new_id()
    lesson = _lesson(term, group_id, teacher_id)
    store.lessons[lesson.id] = lesson
    topic = EmisTopic("Fractions", homework_file_url=HW_URL)
    await _sync(store, term, group_id, topic)
    store.homework_accept[lesson.id] = True  # the teacher turned it on

    tally = await _sync(store, term, group_id, topic)

    assert tally.new_homework == []
    assert store.homework_accept[lesson.id] is True


async def test_a_removed_file_clears_the_link_and_no_default_means_closed() -> None:
    """EMIS dropping the file clears it; a teacher without settings accepts nothing."""
    store = ScheduleStore()
    term = make_term()
    store.terms[term.id] = term
    group_id = new_id()
    lesson = _lesson(term, group_id, new_id())
    store.lessons[lesson.id] = lesson

    await _sync(store, term, group_id, EmisTopic("T", homework_file_url=HW_URL))
    assert store.homework_accept == {lesson.id: False}
    await _sync(store, term, group_id, EmisTopic("T", description=""))

    saved = store.lessons[lesson.id]
    assert (saved.emis_homework_url, saved.emis_topic_description) == (None, None)


def test_the_mapper_keeps_the_emis_homework_columns() -> None:
    """Schedule saves must not wipe what the sync wrote."""
    term = make_term()
    lesson = _lesson(term, new_id(), None)
    lesson.emis_homework_url = HW_URL
    lesson.emis_topic_description = "Read"
    row = LessonOrm(id=lesson.id)
    lesson_apply(row, lesson)

    back = lesson_to_entity(row)

    assert (back.emis_homework_url, back.emis_topic_description) == (HW_URL, "Read")


def test_content_counts_emis_homework_and_submissions() -> None:
    """A lesson with only an EMIS file or a submission is cancelled, not deleted."""
    dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    sql = str(has_content_clause().compile(dialect=dialect))

    assert "emis_homework_url IS NOT NULL" in sql
    assert "homework_submissions" in sql


def _ref(text: str | None) -> LessonRef:
    start = dt.datetime(2026, 10, 5, 8, 30, tzinfo=dt.UTC)
    return LessonRef(
        id=new_id(),
        date=start.date(),
        period=1,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=80),
        subject_id=new_id(),
        subject_name="Math",
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name=None,
        audience=(),
        group_names=(),
        status="scheduled",
        topic=None,
        homework_text=text,
        homework_due_date=None,
    )


def test_lesson_views_count_emis_only_homework() -> None:
    """Schedule lists mark an EMIS-only lesson as having homework."""

    def view(text: str | None, emis: bool) -> LessonView:
        return LessonView(
            ref=_ref(text),
            subject_short=None,
            is_overridden=False,
            changes=None,
            attendance_submitted=False,
            emis_homework=emis,
        )

    assert view(None, True).has_homework
    assert view("Ex. 1", False).has_homework
    assert not view(None, False).has_homework


def test_marks_rows_count_emis_only_homework() -> None:
    """The marks pages mark an EMIS-only lesson as having homework."""
    ref = _ref(None)

    def row(url: str | None) -> MarksLessonRow:
        return MarksLessonRow(
            id=ref.id,
            date=ref.date,
            period=1,
            starts_at=ref.starts_at,
            ends_at=ref.ends_at,
            subject_id=ref.subject_id,
            teacher_id=None,
            room_id=None,
            room_slug=None,
            room_name=None,
            audience=(),
            status="scheduled",
            is_overridden=False,
            changes=None,
            topic=None,
            homework_text=None,
            attendance_roster=None,
            attendance_absent=None,
            emis_homework_url=url,
        )

    assert row(HW_URL).has_homework
    assert not row(None).has_homework
