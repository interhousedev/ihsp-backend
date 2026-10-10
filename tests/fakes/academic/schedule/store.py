"""The shared in-memory state behind the fake schedule repositories."""

import copy
import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from uuid import UUID

from app.modules.academic.domain.curriculum.records import (
    Curriculum,
    SemesterSubject,
)
from app.modules.academic.domain.schedule.group import Group
from app.modules.academic.domain.schedule.lesson import Lesson
from app.modules.academic.domain.schedule.room import Room
from app.modules.academic.domain.schedule.school_days import SATURDAY
from app.modules.academic.domain.schedule.student import Student
from app.modules.academic.domain.schedule.subject import Subject
from app.modules.academic.domain.schedule.term import Term
from app.modules.academic.domain.schedule.timetable_entry import TimetableEntry
from app.shared.notifications import AuditDraft, NotificationDraft


def on_a_saturday(day: dt.date) -> bool:
    """True for a date the SQL reads skip: lessons are never read on a Saturday."""
    return day.isoweekday() == SATURDAY


@dataclass(slots=True)
class ScheduleStore:
    """Tables of the schedule plus what committed transactions wrote."""

    terms: dict[UUID, Term] = field(default_factory=dict)
    groups: dict[UUID, Group] = field(default_factory=dict)
    students: dict[UUID, Student] = field(default_factory=dict)
    subjects: dict[UUID, Subject] = field(default_factory=dict)
    curricula: dict[UUID, Curriculum] = field(default_factory=dict)
    curriculum_subjects: dict[UUID, list[SemesterSubject]] = field(default_factory=dict)
    rooms: dict[UUID, Room] = field(default_factory=dict)
    entries: dict[UUID, TimetableEntry] = field(default_factory=dict)
    lessons: dict[UUID, Lesson] = field(default_factory=dict)
    notifications: list[NotificationDraft] = field(default_factory=list)
    audits: list[AuditDraft] = field(default_factory=list)
    locks: list[UUID] = field(default_factory=list)
    calendar_tokens: dict[UUID, str] = field(default_factory=dict)

    TABLES = (
        "terms",
        "groups",
        "students",
        "subjects",
        "curricula",
        "curriculum_subjects",
        "rooms",
        "entries",
        "lessons",
        "calendar_tokens",
    )

    def snapshot(self) -> dict[str, Any]:
        """Copy the tables so a failed transaction can be rolled back."""
        return {name: copy.deepcopy(getattr(self, name)) for name in self.TABLES}

    def restore(self, snapshot: dict[str, Any]) -> None:
        """Put the tables back as they were at the snapshot."""
        for name, value in snapshot.items():
            setattr(self, name, value)
