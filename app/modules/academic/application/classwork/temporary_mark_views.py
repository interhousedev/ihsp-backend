"""Turns temporary marks into views with student, group, subject and lesson names."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.classwork.people import PeopleDirectory
from app.modules.academic.application.classwork.ports.unit_of_work import (
    TemporaryMarkUnitOfWork,
)
from app.modules.academic.application.classwork.work_off_items import names_of
from app.modules.academic.domain.classwork.records import StudentRecord
from app.modules.academic.domain.classwork.temporary_mark import (
    TemporaryMark,
    TemporaryMarkView,
)


class TemporaryMarkViews:
    """Builds ``TemporaryMarkView`` lists with a fixed number of queries."""

    def __init__(self, people: PeopleDirectory) -> None:
        """Store the people directory."""
        self.people = people

    async def build(
        self,
        uow: TemporaryMarkUnitOfWork,
        marks: Sequence[TemporaryMark],
        locale: str,
    ) -> list[TemporaryMarkView]:
        """Views in the order of ``marks``; marks of vanished lessons are left out."""
        if not marks:
            return []
        lessons = {
            x.id: x
            for x in await uow.lessons.get_many(list({m.lesson_id for m in marks}))
        }
        students = {
            s.user_id: s
            for s in await uow.students.by_ids(list({m.student_id for m in marks}))
        }
        names = await names_of(
            self.people,
            [m.student_id for m in marks] + [x.teacher_id for x in lessons.values()],
        )
        views = []
        for mark in marks:
            lesson = lessons.get(mark.lesson_id)
            if lesson is None:
                continue
            student = students.get(mark.student_id)
            views.append(
                TemporaryMarkView(
                    mark=mark,
                    student_name=names.get(mark.student_id, "?"),
                    group_id=_group_id(student, lesson.groups),
                    group_name=(
                        student.group_name
                        if student is not None
                        else ", ".join(lesson.group_names)
                    ),
                    subject_name=lesson.subject_name(locale),
                    lesson_period=lesson.period,
                    teacher_id=lesson.teacher_id,
                    teacher_name=(
                        ""
                        if lesson.teacher_id is None
                        else names.get(lesson.teacher_id, "")
                    ),
                )
            )
        return views


def _group_id(student: StudentRecord | None, groups: dict[UUID, str]) -> UUID | None:
    """The student's group, else the lesson's first group."""
    if student is not None:
        return student.group_id
    return next(iter(groups), None)
