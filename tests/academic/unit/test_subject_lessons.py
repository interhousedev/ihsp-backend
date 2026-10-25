"""Subject hub lesson list: split by a frozen now, attendance only for the past."""

import datetime as dt
from dataclasses import replace
from uuid import UUID, uuid4

from app.modules.academic.application.marks.list_subject_lessons import (
    ListSubjectLessons,
)
from app.modules.academic.domain.marks.read_models import (
    LessonRow,
    MarkRow,
    StudentContext,
)
from app.modules.academic.domain.marks.subject_lessons import (
    LessonMarkValue,
    SubjectLessonPage,
    build_subject_lessons,
    lesson_results,
)
from app.shared.actor import Actor, Role
from tests.fakes.clock import FixedClock

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
ME = UUID(int=1)
SUBJECT = UUID(int=9)


def _lesson(day_offset: int, *, absent: bool = False, late: bool = False) -> LessonRow:
    start = NOW + dt.timedelta(days=day_offset, hours=1)
    return LessonRow(
        id=uuid4(),
        date=start.date(),
        period=1,
        starts_at=start,
        ends_at=start + dt.timedelta(minutes=80),
        subject_id=UUID(int=9),
        teacher_id=None,
        room_id=None,
        room_slug=None,
        room_name=None,
        audience=(),
        status="scheduled",
        is_overridden=False,
        changes=None,
        topic=f"t{day_offset}",
        homework_text=None,
        attendance_roster=(ME,),
        attendance_absent=(ME,) if absent else (),
        attendance_excused=None,
        attendance_late=(ME,) if late else None,
    )


def _mark(
    value: int,
    *,
    lesson_id: UUID | None,
    day: dt.date | None = None,
    type_: str = "lesson",
    ordinal: int = 1,
) -> MarkRow:
    return MarkRow(
        subject_id=SUBJECT,
        semester=3,
        type=type_,
        value=value,
        date=day or NOW.date(),
        ordinal=ordinal,
        lesson_id=lesson_id,
        created_at=NOW,
    )


def _build(
    lessons: list[LessonRow],
    past_offset: int = 0,
    marks: list[MarkRow] | None = None,
) -> SubjectLessonPage:
    return build_subject_lessons(
        lessons,
        student_id=ME,
        now=NOW,
        marks=marks or [],
        materials={},
        past_offset=past_offset,
    )


def test_lessons_split_by_now() -> None:
    """Past first (newest first), then upcoming within 14 days; later ones hidden."""
    lessons = [_lesson(d) for d in (-3, -1, 2, 13, 15, 30)]
    page = _build(lessons)
    assert [i.past for i in page.items] == [True, True, False, False]
    assert [i.topic for i in page.items] == ["t-1", "t-3", "t2", "t13"]
    assert not any(i.starts_at > NOW + dt.timedelta(days=14) for i in page.items)


def test_absence_and_marks_shown_only_for_past() -> None:
    """A future lesson carries no attendance or mark, even when a mark points at it."""
    past, future = _lesson(-1, absent=True), _lesson(1, absent=True)
    page = build_subject_lessons(
        [past, future],
        student_id=ME,
        now=NOW,
        marks=[_mark(5, lesson_id=past.id), _mark(4, lesson_id=future.id)],
        materials={future.id: 2},
    )
    by_id = {i.lesson_id: i for i in page.items}
    assert by_id[past.id].attendance == "absent"
    assert by_id[past.id].marks == (LessonMarkValue("lesson", 5),)
    assert by_id[future.id].attendance is None and by_id[future.id].marks == ()
    assert by_id[future.id].materials_count == 2


def test_every_mark_of_a_lesson_is_listed_in_type_order() -> None:
    """Several marks on one lesson all show: lesson marks by ordinal, then the rest."""
    past = _lesson(-1)
    page = _build(
        [past],
        marks=[
            _mark(3, lesson_id=past.id, ordinal=2),
            _mark(4, lesson_id=past.id, type_="midterm"),
            _mark(5, lesson_id=past.id, ordinal=1),
        ],
    )
    assert page.items[0].marks == (
        LessonMarkValue("lesson", 5),
        LessonMarkValue("lesson", 3),
        LessonMarkValue("midterm", 4),
    )


def test_unlinked_mark_goes_to_the_first_lesson_of_its_date() -> None:
    """An unlinked mark (synced before its lesson) lands on the date's first lesson."""
    morning = _lesson(-1)
    afternoon = replace(
        _lesson(-1), period=2, starts_at=morning.starts_at + dt.timedelta(hours=3)
    )
    page = _build(
        [afternoon, morning], marks=[_mark(4, lesson_id=None, day=morning.date)]
    )
    by_id = {i.lesson_id: i for i in page.items}
    assert by_id[morning.id].marks == (LessonMarkValue("lesson", 4),)
    assert by_id[afternoon.id].marks == ()


def test_unlinked_mark_on_a_day_without_a_scheduled_lesson_is_dropped() -> None:
    """No lesson of the subject on that date: the unlinked mark is not listed."""
    past = _lesson(-1)
    page = _build([past], marks=[_mark(5, lesson_id=None, day=dt.date(2026, 9, 1))])
    assert page.items[0].marks == ()


def test_mark_linked_to_a_lesson_outside_the_list_is_not_repeated() -> None:
    """A mark linked to a lesson outside the list is not moved to another lesson."""
    past = _lesson(-1)
    outside = uuid4()
    page = _build([past], marks=[_mark(5, lesson_id=outside, day=past.date)])
    assert page.items[0].marks == ()


def test_present_and_paging() -> None:
    """Show-more pages the past lessons; the upcoming ones come with the first page."""
    lessons = [_lesson(-d) for d in range(1, 26)]
    first = _build(lessons)
    assert len(first.items) == 10 and first.has_more_past
    assert first.items[0].attendance == "present"
    last = _build(lessons, 20)
    assert len(last.items) == 5 and not last.has_more_past


def test_lesson_results_only_for_lessons_started_before_now() -> None:
    """The calendar dot and mark exist only once the lesson has started."""
    past, future = _lesson(-1, absent=True), _lesson(1, absent=True)
    rows = lesson_results(
        [past, future], student_id=ME, now=NOW, marks={past.id: 4, future.id: 5}
    )
    assert rows == [(past.id, "absent", 4)]


class _Reader:
    """Just the reads `ListSubjectLessons` makes."""

    def __init__(
        self, lessons: list[LessonRow], marks: list[MarkRow] | None = None
    ) -> None:
        self._lessons = lessons
        self._marks = marks or []

    async def student_context(self, user_id: UUID) -> StudentContext:
        return StudentContext(
            user_id=user_id,
            group_id=uuid4(),
            group_name="g",
            subgroup=None,
            current_semester=3,
            curriculum_subject_ids=(UUID(int=9),),
            synced_at=None,
            backfilled_at=None,
        )

    async def results(self, *_: object) -> list[object]:
        return []

    async def terms(self) -> list[tuple[dt.date, dt.date]]:
        return [(dt.date(2026, 9, 1), dt.date(2026, 12, 31))]

    async def lessons(self, _ctx: object, **_kw: object) -> list[LessonRow]:
        return self._lessons

    async def marks(self, *_: object, **_kw: object) -> list[MarkRow]:
        return self._marks


class _Uow:
    def __init__(self, reader: _Reader) -> None:
        self.reader = reader

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *_: object) -> None:
        return None


class _Links:
    async def resources_for_lessons(self, _ids: object) -> dict[UUID, list[object]]:
        return {}


async def test_use_case_uses_the_frozen_clock() -> None:
    """The query splits by the injected clock, not the wall clock."""
    lessons = [_lesson(-2, absent=True), _lesson(3), _lesson(40)]
    reader = _Reader(lessons)
    use_case = ListSubjectLessons(
        uow_factory=lambda: _Uow(reader),  # type: ignore[arg-type,return-value]
        links=_Links(),  # type: ignore[arg-type]
        clock=FixedClock(NOW),
    )
    actor = Actor(user_id=ME, roles=frozenset({Role.STUDENT}))

    result = await use_case.execute(actor, UUID(int=9))

    assert [i["past"] for i in result["items"]] == [True, False]
    assert result["items"][0]["attendance"] == "absent"
    assert result["items"][1]["attendance"] is None
    assert result["has_more_past"] is False


async def test_use_case_returns_every_mark_as_a_list() -> None:
    """A lesson with a linked and an unlinked mark lists both in the response."""
    past = _lesson(-2)
    reader = _Reader(
        [past],
        marks=[
            _mark(5, lesson_id=past.id),
            _mark(4, lesson_id=None, day=past.date, ordinal=2),
        ],
    )
    use_case = ListSubjectLessons(
        uow_factory=lambda: _Uow(reader),  # type: ignore[arg-type,return-value]
        links=_Links(),  # type: ignore[arg-type]
        clock=FixedClock(NOW),
    )
    actor = Actor(user_id=ME, roles=frozenset({Role.STUDENT}))

    result = await use_case.execute(actor, SUBJECT)

    assert result["items"][0]["marks"] == [
        {"type": "lesson", "value": 5},
        {"type": "lesson", "value": 4},
    ]
    assert "mark" not in result["items"][0]


def test_late_lesson_result_is_late() -> None:
    """A late student is present for the rates but shows as late."""
    past = _lesson(-1, late=True)
    (row,) = lesson_results([past], student_id=ME, now=NOW, marks={})
    assert row[1] == "late"
