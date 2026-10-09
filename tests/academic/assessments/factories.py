"""Builders of assessment records for the tests."""

import datetime as dt
from uuid import UUID, uuid4

from app.modules.academic.domain.assessments.periods import TermControls
from app.modules.academic.domain.assessments.records import (
    Assessment,
    LessonCandidate,
    NewAssessment,
)
from app.modules.academic.domain.schedule.term import ControlPeriod, ControlPeriods

GROUP = UUID(int=100)
OTHER_GROUP = UUID(int=200)
MATH = UUID(int=1)
PHYSICS = UUID(int=2)
TERM = UUID(int=900)
STAMP = dt.datetime(2026, 10, 1, tzinfo=dt.UTC)


def period(start: str, end: str) -> ControlPeriod:
    """A control week from ISO dates."""
    return ControlPeriod(
        start=dt.date.fromisoformat(start), end=dt.date.fromisoformat(end)
    )


def make_term(**periods: ControlPeriod) -> TermControls:
    """The autumn term 2026-09-01..2026-12-31 with the given control weeks."""
    return TermControls(
        term_id=TERM,
        starts_on=dt.date(2026, 9, 1),
        ends_on=dt.date(2026, 12, 31),
        periods=ControlPeriods(**periods),
    )


def standard_term() -> TermControls:
    """A term with all three control weeks set."""
    return make_term(
        midterm_1=period("2026-10-19", "2026-10-24"),
        midterm_2=period("2026-11-23", "2026-11-28"),
        final=period("2026-12-14", "2026-12-19"),
    )


def make_assessment(**kwargs: object) -> Assessment:
    """A planned math midterm of the group on 2026-10-21."""
    fields: dict[str, object] = {
        "id": uuid4(),
        "subject_id": MATH,
        "audience": (str(GROUP),),
        "kind": "midterm",
        "title": "",
        "date": dt.date(2026, 10, 21),
        "lesson_id": None,
        "starts_at": None,
        "room": None,
        "status": "planned",
        "source": "teacher",
        "note": None,
        "created_by": None,
        "created_at": STAMP,
        "updated_at": STAMP,
        "control": None,
    }
    fields.update(kwargs)
    return Assessment(**fields)  # type: ignore[arg-type]


def make_new(**kwargs: object) -> NewAssessment:
    """A new math midterm of the group on 2026-10-21."""
    fields: dict[str, object] = {
        "subject_id": MATH,
        "audience": (str(GROUP),),
        "kind": "midterm",
        "title": "",
        "date": dt.date(2026, 10, 21),
        "lesson_id": None,
        "starts_at": None,
        "room": None,
        "status": "planned",
        "source": "teacher",
        "note": None,
        "created_by": None,
        "control": None,
    }
    fields.update(kwargs)
    return NewAssessment(**fields)  # type: ignore[arg-type]


def make_lesson(**kwargs: object) -> LessonCandidate:
    """An EMIS midterm lesson of math for the group on 2026-10-21."""
    day = kwargs.pop("date", dt.date(2026, 10, 21))
    assert isinstance(day, dt.date)
    fields: dict[str, object] = {
        "lesson_id": uuid4(),
        "subject_id": MATH,
        "audience": (str(GROUP),),
        "date": day,
        "starts_at": dt.datetime.combine(day, dt.time(4, 0), tzinfo=dt.UTC),
        "kind": "midterm",
        "topic": None,
        "room": None,
    }
    fields.update(kwargs)
    return LessonCandidate(**fields)  # type: ignore[arg-type]
