"""Terms, bell schedules and moved study days (ACA-4)."""

import datetime as dt
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Annotated, Any, Literal
from uuid import UUID

from app.modules.academic.domain.schedule.errors import (
    TermBellsInvalidError,
    TermDatesInvalidError,
    TermMovedDayInvalidError,
    TermNonStudyDayInvalidError,
)

from pydantic import BaseModel, ConfigDict, Field, PlainSerializer, TypeAdapter

STUDY_WEEKDAYS = (1, 2, 3, 4, 5, 6)

HourMinute = Annotated[
    dt.time,
    PlainSerializer(
        lambda value: value.strftime("%H:%M"), return_type=str, when_used="json"
    ),
]


BellSource = Literal["manual", "emis"]


class Bell(BaseModel):
    """Start and end of one period on some weekdays (jsonb of Term.bells).

    ``source`` says who set the bell: Administration (``manual``) or the EMIS
    ``class-hours`` sync (``emis``), which keeps its bells equal to EMIS.
    """

    model_config = ConfigDict(frozen=True)

    period: int = Field(ge=1, le=20)
    start: HourMinute
    end: HourMinute
    weekdays: list[int] = Field(min_length=1)
    source: BellSource = "manual"


class MovedDay(BaseModel):
    """A date that follows another weekday's timetable (jsonb of Term.moved_days)."""

    model_config = ConfigDict(frozen=True)

    date: dt.date
    follows_weekday: int


_BELLS = TypeAdapter(list[Bell])
_MOVED_DAYS = TypeAdapter(list[MovedDay])


def bells_from_json(raw: Any) -> list[Bell]:
    """Validate the jsonb stored in Term.bells."""
    return _BELLS.validate_python(raw or [])


def bells_to_json(bells: Sequence[Bell]) -> list[dict[str, Any]]:
    """Serialize bells for the jsonb column ("08:30" times)."""
    dumped: list[dict[str, Any]] = _BELLS.dump_python(list(bells), mode="json")
    return dumped


def moved_days_from_json(raw: Any) -> list[MovedDay]:
    """Validate the jsonb stored in Term.moved_days."""
    return _MOVED_DAYS.validate_python(raw or [])


def moved_days_to_json(days: Sequence[MovedDay]) -> list[dict[str, Any]]:
    """Serialize moved days for the jsonb column."""
    dumped: list[dict[str, Any]] = _MOVED_DAYS.dump_python(list(days), mode="json")
    return dumped


@dataclass(slots=True)
class Term:
    """A half of an academic year with its calendar."""

    id: UUID
    academic_year: str
    half: int
    starts_on: dt.date
    ends_on: dt.date
    bells: list[Bell] = field(default_factory=list)
    non_study_days: list[dt.date] = field(default_factory=list)
    moved_days: list[MovedDay] = field(default_factory=list)

    def contains(self, day: dt.date) -> bool:
        """Return True if the day lies inside the term."""
        return self.starts_on <= day <= self.ends_on


def validate_term(term: Term) -> None:
    """Check the rules of Step 1: dates, bells, non-study days, moved days."""
    if not term.starts_on < term.ends_on:
        raise TermDatesInvalidError()
    _validate_bells(term.bells)
    for day in term.non_study_days:
        if not term.contains(day):
            raise TermNonStudyDayInvalidError(params={"date": day.isoformat()})
    for moved in term.moved_days:
        if moved.follows_weekday not in STUDY_WEEKDAYS:
            raise TermMovedDayInvalidError(params={"date": moved.date.isoformat()})


def _validate_bells(bells: Sequence[Bell]) -> None:
    seen: set[tuple[int, int]] = set()
    for bell in bells:
        if not bell.start < bell.end:
            raise TermBellsInvalidError(params={"period": bell.period})
        for weekday in bell.weekdays:
            slot = (bell.period, weekday)
            if weekday not in STUDY_WEEKDAYS or slot in seen:
                raise TermBellsInvalidError(
                    params={"period": bell.period, "weekday": weekday}
                )
            seen.add(slot)


def pick_current_term(terms: Sequence[Term], today: dt.date) -> Term | None:
    """Return the term containing today, else the next one, else the last one."""
    ordered = sorted(terms, key=lambda term: term.starts_on)
    for term in ordered:
        if term.contains(today):
            return term
    for term in ordered:
        if term.starts_on > today:
            return term
    return ordered[-1] if ordered else None
