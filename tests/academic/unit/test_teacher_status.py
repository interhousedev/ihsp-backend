"""Which lesson a teacher teaches now and which is next (frozen clock)."""

import datetime as dt

from app.modules.academic.domain.schedule.teacher_status import current_and_next
from app.shared.contracts.academic import LessonRef
from app.shared.ids import new_id

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def _ref(
    start_minutes: int, *, status: str = "scheduled", length: int = 45
) -> LessonRef:
    begin = NOW + dt.timedelta(minutes=start_minutes)
    return LessonRef(
        id=new_id(),
        date=begin.date(),
        period=1,
        starts_at=begin,
        ends_at=begin + dt.timedelta(minutes=length),
        subject_id=new_id(),
        subject_name="Math",
        teacher_id=new_id(),
        room_id=None,
        room_slug=None,
        room_name="305",
        audience=(),
        group_names=(),
        status=status,  # type: ignore[arg-type]
        topic=None,
        homework_text=None,
        homework_due_date=None,
    )


def test_a_running_lesson_is_current_and_the_following_one_is_next() -> None:
    running, later, latest = _ref(-10), _ref(60), _ref(120)

    current, upcoming = current_and_next([latest, later, running], NOW)

    assert current is running and upcoming is later


def test_the_lesson_starting_exactly_now_is_current_and_one_ending_now_is_not() -> None:
    starting, ended = _ref(0), _ref(-45)

    current, upcoming = current_and_next([ended, starting], NOW)

    assert current is starting and upcoming is None


def test_cancelled_lessons_are_ignored() -> None:
    cancelled_now, cancelled_next = _ref(-5, status="cancelled"), _ref(
        30, status="cancelled"
    )
    real_next = _ref(90)

    current, upcoming = current_and_next(
        [cancelled_now, cancelled_next, real_next], NOW
    )

    assert current is None and upcoming is real_next


def test_no_lessons_gives_nothing() -> None:
    assert current_and_next([], NOW) == (None, None)
