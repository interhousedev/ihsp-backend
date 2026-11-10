"""Builds the ``AttendanceSheet`` JSON of a lesson (STF-8)."""

import datetime as dt
from collections.abc import Collection, Sequence
from typing import Any
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.excuse_coverage import (
    ExcuseCoverage,
)
from app.modules.academic.domain.classwork.attendance_rules import attendance_editable
from app.modules.academic.domain.classwork.excuse_ref import excuse_of_mark
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.domain.classwork.roster import Roster
from app.modules.academic.domain.classwork.work_off import WorkOff
from app.shared.actor import Actor


class AttendanceSheetBuilder:
    """Combines the lesson's saved lists with the current roster."""

    def __init__(
        self, people: PeopleDirectory, excuse_coverage: ExcuseCoverage
    ) -> None:
        """Store the people directory and the excuse rule."""
        self.people = people
        self.excuse_coverage = excuse_coverage

    async def build(
        self,
        lesson: Lesson,
        roster: Roster,
        actor: Actor,
        today: dt.date,
        *,
        visible_groups: Collection[UUID] | None = None,
        work_offs: Sequence[WorkOff] = (),
    ) -> dict[str, Any]:
        """Return the sheet; ``visible_groups`` limits it to a curator's groups.

        ``work_offs`` are the lesson's tasks; only visible students' ones are shown.
        """
        students = [
            student
            for student in roster.entries
            if visible_groups is None or student.group_id in visible_groups
        ]
        absent = set(lesson.attendance_absent or ())
        late = set(lesson.attendance_late or ())
        saved = set(lesson.attendance_roster or ())
        expected = roster.expected_ids()
        marks = lesson.attendance_excused or {}
        excuses = (await self.excuse_coverage.effective([lesson])).get(lesson.id, {})
        items = []
        for position, student in enumerate(students):
            mark = marks.get(str(student.user_id))
            is_absent = student.user_id in absent
            excuse = excuses.get(student.user_id)
            items.append(
                {
                    "position": position,
                    "user_id": str(student.user_id),
                    "first_name": student.first_name,
                    "last_name": student.last_name,
                    "group_name": student.group_name,
                    "subgroup_unset": student.user_id not in expected,
                    "absent": is_absent,
                    "late": student.user_id in late,
                    "excused": excuse is not None,
                    "excuse": None if excuse is None else excuse.as_dict(),
                    "excuse_comment": (
                        None
                        if excuse_of_mark(mark) or not mark
                        else mark.get("comment")
                    ),
                    # Unassigned students count only once the teacher marked them.
                    "counted": (
                        student.user_id in saved
                        if lesson.submitted
                        else student.user_id in expected
                    ),
                }
            )
        author = await self.people.person(lesson.attendance_by)
        editable = lesson.scheduled and attendance_editable(lesson, actor)
        return {
            "lesson_id": str(lesson.id),
            "submitted": lesson.submitted,
            "version": lesson.attendance_version,
            "editable": editable,
            "roster": items,
            "submitted_at": (
                lesson.attendance_at.isoformat() if lesson.attendance_at else None
            ),
            "submitted_by": None if author is None else author.to_json(),
            "work_offs": [
                w.to_json()
                for w in work_offs
                if any(w.student_id == s.user_id for s in students)
            ],
        }
