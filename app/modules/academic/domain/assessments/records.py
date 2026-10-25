"""Assessments (controls) as plain records, without any framework."""

import datetime as dt
from dataclasses import dataclass
from typing import Literal
from uuid import UUID

from app.modules.academic.domain.schedule.term import ControlName

AssessmentKind = Literal["midterm", "final", "other"]
AssessmentStatus = Literal["planned", "tentative", "cancelled"]
AssessmentSource = Literal["teacher", "admin", "emis", "head_student"]

KINDS: tuple[AssessmentKind, ...] = ("midterm", "final", "other")
STATUSES: tuple[AssessmentStatus, ...] = ("planned", "tentative", "cancelled")
SOURCES: tuple[AssessmentSource, ...] = ("teacher", "admin", "emis", "head_student")


@dataclass(frozen=True, slots=True)
class Assessment:
    """One control of a subject for an audience on a date.

    ``control`` is the control week of the term (midterm 1, midterm 2, final) the
    control belongs to. ``tentative`` marks a date nobody in charge has confirmed: it
    came from EMIS outside any control week, or from a head student. ``cancelled``
    hides the control and keeps a dismissed EMIS suggestion from coming back.
    """

    id: UUID
    subject_id: UUID
    audience: tuple[str, ...]
    kind: AssessmentKind
    title: str
    date: dt.date
    lesson_id: UUID | None
    starts_at: dt.datetime | None
    room: str | None
    status: AssessmentStatus
    source: AssessmentSource
    note: str | None
    created_by: UUID | None
    created_at: dt.datetime
    updated_at: dt.datetime
    control: ControlName | None = None


@dataclass(frozen=True, slots=True)
class NewAssessment:
    """The fields of a control that is about to be stored."""

    subject_id: UUID
    audience: tuple[str, ...]
    kind: AssessmentKind
    title: str
    date: dt.date
    lesson_id: UUID | None
    starts_at: dt.datetime | None
    room: str | None
    status: AssessmentStatus
    source: AssessmentSource
    note: str | None
    created_by: UUID | None
    control: ControlName | None = None


@dataclass(frozen=True, slots=True)
class LessonCandidate:
    """A lesson EMIS marked as a midterm or a final, as the generator reads it."""

    lesson_id: UUID
    subject_id: UUID
    audience: tuple[str, ...]
    date: dt.date
    starts_at: dt.datetime
    kind: AssessmentKind
    topic: str | None
    room: str | None
