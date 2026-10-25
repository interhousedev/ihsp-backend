"""Whose subject notebook it is: which teachers' materials and which groups it gets."""

from uuid import UUID

from app.modules.notebooks.domain.default_materials import MaterialAudience
from app.modules.notebooks.domain.entities import Notebook
from app.shared.contracts.academic import LessonRef, ScheduleQueries


def parse_key(key: str) -> tuple[UUID, int | None]:
    """Split an audience key ("<group>" or "<group>:<subgroup>")."""
    group, _, sub = key.partition(":")
    return UUID(group), (int(sub) if sub else None)


async def audience_of(
    schedule: ScheduleQueries, notebook: Notebook, lessons: list[LessonRef]
) -> MaterialAudience:
    """The audience of a subject notebook, from the lessons that feed it.

    A student's notebook follows the teachers of their lessons of the subject and the
    student's own group and subgroup. A teacher's notebook (it has a `group_id`)
    follows the teacher and the groups (with subgroups) they teach the subject to.
    """
    if notebook.group_id is not None:
        groups = {
            parse_key(key)
            for lesson in lessons
            for key in lesson.audience
            if parse_key(key)[0] == notebook.group_id
        }
        return MaterialAudience(
            teacher_ids=frozenset({notebook.owner_id}),
            groups=tuple(sorted(groups, key=lambda g: (str(g[0]), g[1] or 0))),
            is_student=False,
        )
    student = await schedule.get_student(notebook.owner_id)
    teachers = frozenset(x.teacher_id for x in lessons if x.teacher_id is not None)
    placed = () if student is None else ((student.group_id, student.subgroup),)
    return MaterialAudience(teacher_ids=teachers, groups=placed, is_student=True)
