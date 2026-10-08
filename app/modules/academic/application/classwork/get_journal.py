"""Use case: the journal grid of a subject and audience (STF-9, UF-STF-07)."""

import datetime as dt
from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.journal_options import (
    audience_key_of,
)
from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    ViewUnitOfWork,
)
from app.modules.academic.application.classwork.roster_loader import RosterLoader
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.attendance_rules import attendance_editable
from app.modules.academic.domain.classwork.errors import JournalNotFoundError
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.names import localized
from app.modules.academic.domain.classwork.records import JournalOption, TermRecord
from app.modules.academic.domain.classwork.roster import RosterStudent
from app.shared.actor import Actor, Role
from app.shared.clock import Clock, local_today


def parse_audience_key(value: str) -> tuple[str, ...]:
    """Split and validate an ``audience_key``."""
    keys = tuple(sorted(part for part in value.split(",") if part))
    try:
        for key in keys:
            audience_keys.parse(key)
    except ValueError as error:
        raise JournalNotFoundError(params={"audience_key": value}) from error
    if not keys:
        raise JournalNotFoundError(params={"audience_key": value})
    return keys


class GetJournal:
    """Students as rows, the term's lessons as columns."""

    def __init__(
        self,
        uow_factory: Callable[[], ViewUnitOfWork],
        clock: Clock,
        people: PeopleDirectory,
        roster_loader: RosterLoader,
        edit_days: int,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.people = people
        self.roster_loader = roster_loader
        self.edit_days = edit_days

    async def _term(
        self, uow: ViewUnitOfWork, term_id: UUID | None, today: dt.date
    ) -> TermRecord:
        term = (
            await uow.results.term(term_id)
            if term_id
            else await uow.results.current_term(today)
        )
        if term is None:
            raise JournalNotFoundError(params={"term_id": str(term_id)})
        return term

    async def execute(
        self,
        actor: Actor,
        subject_id: UUID,
        audience_key: str,
        term_id: UUID | None,
    ) -> dict[str, Any]:
        """Return the ``Journal`` JSON; teachers see only journals they teach."""
        keys = parse_audience_key(audience_key)
        today = local_today(self.clock)
        locale = await self.people.locale(actor.user_id)
        async with self.uow_factory() as uow:
            term = await self._term(uow, term_id, today)
            matched: JournalOption | None = None
            if not actor.has(Role.ADMIN):
                options = await uow.journal.options(
                    actor.user_id, term.starts_on, term.ends_on
                )
                matched = next(
                    (
                        o
                        for o in options
                        if o.subject_id == subject_id
                        and tuple(sorted(o.audience)) == keys
                    ),
                    None,
                )
                if matched is None:
                    raise JournalNotFoundError(params={"audience_key": audience_key})
            lessons = await uow.journal.lessons(
                subject_id, keys, term.starts_on, term.ends_on
            )
            saved = {
                uid for lesson in lessons for uid in lesson.attendance_roster or ()
            }
            roster = await self.roster_loader.load_for_keys(uow, keys, saved)
            marks = await uow.journal.marks_by_cell([lesson.id for lesson in lessons])
            students = await uow.students.by_ids([s.user_id for s in roster.entries])
            current = term.starts_on <= today <= term.ends_on
            semester_of = {s.user_id: s.current_semester for s in students}
            semester_marks = await self._semester_marks(
                uow, subject_id, semester_of, current
            )
        subject = _subject(matched, lessons, subject_id, locale)
        return {
            "subject": subject,
            "audience_key": audience_key_of(keys),
            "lessons": [self._lesson(lesson, actor, today) for lesson in lessons],
            "students": [
                _student_row(
                    student, lessons, marks, semester_marks.get(student.user_id)
                )
                for student in roster.entries
            ],
        }

    def _lesson(self, lesson: Lesson, actor: Actor, today: dt.date) -> dict[str, Any]:
        return {
            "id": str(lesson.id),
            "date": lesson.date.isoformat(),
            "topic": lesson.topic,
            "attendance_submitted": lesson.submitted,
            "editable": attendance_editable(lesson, actor, today, self.edit_days),
            "version": lesson.attendance_version,
        }

    @staticmethod
    async def _semester_marks(
        uow: ViewUnitOfWork,
        subject_id: UUID,
        semester_of: dict[UUID, int | None],
        current: bool,
    ) -> dict[UUID, float | None]:
        if not current:
            return {}
        result: dict[UUID, float | None] = {}
        for semester in {s for s in semester_of.values() if s is not None}:
            ids = [uid for uid, value in semester_of.items() if value == semester]
            result.update(await uow.journal.semester_marks(ids, subject_id, semester))
        return result


def _subject(
    matched: JournalOption | None,
    lessons: list[Lesson],
    subject_id: UUID,
    locale: str,
) -> dict[str, Any]:
    names: dict[str, str] = {}
    short: str | None = None
    if matched is not None:
        names, short = matched.subject_names, matched.subject_short
    elif lessons:
        names, short = lessons[0].subject_names, lessons[0].subject_short
    name = localized(names, locale)
    return {"id": str(subject_id), "name": name, "short_name": short or name}


def _student_row(
    student: RosterStudent,
    lessons: list[Lesson],
    marks: dict[tuple[UUID, UUID], list[int]],
    semester_mark: float | None,
) -> dict[str, Any]:
    cells = []
    for lesson in lessons:
        absent = student.user_id in (lesson.attendance_absent or ())
        cells.append(
            {
                "lesson_id": str(lesson.id),
                "absent": absent,
                "excused": absent and str(student.user_id) in lesson.excused_ids(),
                "marks": marks.get((lesson.id, student.user_id), []),
            }
        )
    return {
        "user_id": str(student.user_id),
        "first_name": student.first_name,
        "last_name": student.last_name,
        "cells": cells,
        "absences": sum(1 for cell in cells if cell["absent"]),
        "semester_mark": semester_mark,
    }
