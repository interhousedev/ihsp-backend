"""Inputs of the assessment use cases."""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain.assessments.edit import AudienceInput
from app.modules.academic.domain.assessments.records import (
    AssessmentKind,
    AssessmentSource,
    AssessmentStatus,
)
from app.modules.academic.domain.schedule.term import ControlName


@dataclass(frozen=True, slots=True)
class AssessmentInput:
    """A new control as staff type it in."""

    subject_id: UUID
    audience: AudienceInput
    kind: AssessmentKind
    date: dt.date
    title: str = ""
    starts_at: dt.datetime | None = None
    room: str | None = None
    note: str | None = None
    lesson_id: UUID | None = None
    control: ControlName | None = None


@dataclass(frozen=True, slots=True)
class ProposalInput:
    """A date a head student suggests for their own group."""

    subject_id: UUID
    kind: AssessmentKind
    date: dt.date
    title: str = ""
    starts_at: dt.datetime | None = None
    room: str | None = None
    note: str | None = None
    control: ControlName | None = None


@dataclass(frozen=True, slots=True)
class StaffFilters:
    """Filters of the staff and admin listings."""

    since: dt.date | None = None
    until: dt.date | None = None
    subject_id: UUID | None = None
    group_id: UUID | None = None
    kind: AssessmentKind | None = None
    status: AssessmentStatus | None = None
    source: AssessmentSource | None = None
    undated: bool = False
