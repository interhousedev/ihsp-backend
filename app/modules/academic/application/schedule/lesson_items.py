"""Building LessonItem dicts (the JSON shape of the API contract)."""

from collections.abc import Sequence
from typing import Any

from app.modules.academic.application.schedule.common import person_map
from app.modules.academic.application.schedule.results import PersonData
from app.modules.academic.domain.lesson_item import lesson_item
from app.modules.academic.domain.schedule.audience_display import audience_items
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.shared.contracts.identity import IdentityDirectory


def _person(person: PersonData | None) -> dict[str, Any] | None:
    if person is None:
        return None
    return {
        "id": str(person.id),
        "first_name": person.first_name,
        "last_name": person.last_name,
    }


async def build_lesson_items(
    views: Sequence[LessonView], identity: IdentityDirectory
) -> list[dict[str, Any]]:
    """Return LessonItem dicts with teachers resolved through the identity module."""
    people = await person_map(identity, [v.ref.teacher_id for v in views])
    items: list[dict[str, Any]] = []
    for view in views:
        teacher = people.get(view.ref.teacher_id) if view.ref.teacher_id else None
        items.append(
            lesson_item(
                view.ref,
                teacher=_person(teacher),
                subject_short=view.subject_short,
                audience=audience_items(view.ref.audience, view.audience_groups),
                attendance_submitted=view.attendance_submitted,
                has_homework=view.has_homework,
                is_overridden=view.is_overridden,
                changes=view.changes,
                absent_count=view.absent_count,
                late_count=view.late_count,
            )
        )
    return items
