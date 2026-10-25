"""Who may open a subject group: its teachers of the subject, and Administration.

A teacher's groups come from their lessons of the subject (the audience keys
"<group>" or "<group>:<subgroup>"). A teacher of one subgroup sees only that
subgroup's students (and the students without a subgroup).
"""

import datetime as dt
from dataclasses import dataclass
from uuid import UUID

from app.modules.academic.domain.schedule.errors import NotTeachingGroupError
from app.shared.actor import Actor, Role
from app.shared.contracts.academic import LessonRef, ScheduleQueries, StudentRef

WINDOW_DAYS = 180  # the lessons that prove a teacher teaches a group: half a year


@dataclass(frozen=True, slots=True)
class TaughtGroup:
    """The subject group the caller may see.

    `scope` holds the subgroups the caller teaches; None in it means the whole group.
    """

    subject_name: str
    group_name: str
    scope: frozenset[int | None]
    students: list[StudentRef]
    lessons: list[LessonRef]


def parse_key(key: str) -> tuple[str, int | None]:
    """Split an audience key ("<group>" or "<group>:<subgroup>")."""
    group, _, sub = key.partition(":")
    return group, (int(sub) if sub else None)


def in_subgroup(student: StudentRef, subgroup: int | None) -> bool:
    """True when the student belongs to the subgroup (None: the whole group).

    The one place that reads subgroup membership: students without a subgroup
    count as members of both, as in the audience of their lessons.
    """
    return subgroup is None or student.subgroup in (None, subgroup)


def _matches(lesson: LessonRef, group_id: UUID, subgroup: int | None) -> bool:
    for key in lesson.audience:
        group, sub = parse_key(key)
        if group == str(group_id) and (subgroup is None or sub in (None, subgroup)):
            return True
    return False


def _scope(lessons: list[LessonRef], group_id: UUID) -> frozenset[int | None]:
    found: set[int | None] = set()
    for lesson in lessons:
        for key in lesson.audience:
            group, sub = parse_key(key)
            if group == str(group_id):
                found.add(sub)
    return frozenset(found)


def _visible(
    student: StudentRef, subgroup: int | None, scope: frozenset[int | None]
) -> bool:
    if not in_subgroup(student, subgroup):
        return False
    if subgroup is not None or None in scope:
        return True
    return student.subgroup is None or student.subgroup in scope


async def _group_students(
    schedule: ScheduleQueries, group_id: UUID
) -> list[StudentRef]:
    students = []
    for user_id in await schedule.group_user_ids([group_id]):
        student = await schedule.get_student(user_id)
        if student is not None and student.group_id == group_id:
            students.append(student)
    return students


async def _candidate_lessons(
    schedule: ScheduleQueries,
    actor: Actor,
    students: list[StudentRef],
    today: dt.date,
) -> list[LessonRef]:
    """The teacher's lessons; for Administration, the lessons of one student."""
    start = today - dt.timedelta(days=WINDOW_DAYS)
    end = today + dt.timedelta(days=WINDOW_DAYS)
    if not actor.has(Role.ADMIN):
        return await schedule.lessons_for_teacher(actor.user_id, start, end)
    if not students:
        return []
    return await schedule.lessons_for_student(students[0].user_id, start, end)


async def taught_group(
    schedule: ScheduleQueries,
    actor: Actor,
    subject_id: UUID,
    group_id: UUID,
    subgroup: int | None,
    today: dt.date,
) -> TaughtGroup:
    """The group as the caller may see it; raise when they do not teach it."""
    everyone = await _group_students(schedule, group_id)
    sample = [s for s in everyone if in_subgroup(s, subgroup)]
    lessons = [
        lesson
        for lesson in await _candidate_lessons(schedule, actor, sample, today)
        if lesson.subject_id == subject_id and _matches(lesson, group_id, subgroup)
    ]
    scope = frozenset({None}) if actor.has(Role.ADMIN) else _scope(lessons, group_id)
    if not scope:
        raise NotTeachingGroupError()
    lessons.sort(key=lambda x: (x.date, x.period))
    return TaughtGroup(
        subject_name=lessons[0].subject_name if lessons else "",
        group_name=_group_name(everyone, lessons),
        scope=scope,
        students=[s for s in everyone if _visible(s, subgroup, scope)],
        lessons=lessons,
    )


def _group_name(students: list[StudentRef], lessons: list[LessonRef]) -> str:
    if students:
        return students[0].group_name
    for lesson in lessons:
        for label in lesson.group_names:
            return label.rsplit("/", 1)[0]
    return ""
