"""JSON views of contract objects: PersonRef, SubjectRef, LessonItem, HomeworkItem.

The contracts carry less than the full API types: a `LessonRef` has no subject short
name, override flags or attendance state. These views fill what the contract knows and
use the neutral value for the rest (`is_overridden` False, `changes` None,
`attendance_submitted` False, `updated` False).
"""

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from app.interfaces.http.v1.composition.ports import JsonObject
from app.shared.contracts.academic import LessonRef
from app.shared.contracts.identity import IdentityDirectory, UserRef

USER_BATCH = 500


async def load_users(
    identity: IdentityDirectory, user_ids: Iterable[UUID]
) -> dict[UUID, UserRef]:
    """Load users in batches; unknown ids are simply missing from the result."""
    unique = sorted(set(user_ids), key=str)
    users: dict[UUID, UserRef] = {}
    for start in range(0, len(unique), USER_BATCH):
        users.update(await identity.get_users(unique[start : start + USER_BATCH]))
    return users


def person_ref(user: UserRef) -> JsonObject:
    """Return `PersonRef`."""
    return {
        "id": user.id,
        "first_name": user.first_name,
        "last_name": user.last_name,
    }


def subject_ref(subject_id: UUID, name: str) -> JsonObject:
    """Return `SubjectRef`; the contract has no short name, so it repeats the name."""
    return {"id": subject_id, "name": name, "short_name": name}


def audience_items(ref: LessonRef) -> list[JsonObject]:
    """Return `AudienceItem` dicts from the audience keys `<group>[:<subgroup>]`."""
    items: list[JsonObject] = []
    for index, key in enumerate(ref.audience):
        group, _, sub = key.partition(":")
        try:
            group_id = UUID(group)
            subgroup = int(sub) if sub else None
        except ValueError:
            continue
        label = ref.group_names[index] if index < len(ref.group_names) else group
        # Labels of subgroup keys read "2TN2/1"; the item wants the bare group name.
        name = label.rsplit("/", 1)[0] if subgroup is not None else label
        items.append({"group_id": group_id, "group_name": name, "subgroup": subgroup})
    return items


def lesson_item(ref: LessonRef, teachers: Mapping[UUID, UserRef]) -> JsonObject:
    """Return `LessonItem` built from a `LessonRef`."""
    teacher = teachers.get(ref.teacher_id) if ref.teacher_id else None
    room = None
    if ref.room_id is not None:
        room = {"id": ref.room_id, "slug": ref.room_slug, "name": ref.room_name}
    return {
        "id": ref.id,
        "date": ref.date,
        "period": ref.period,
        "starts_at": ref.starts_at,
        "ends_at": ref.ends_at,
        "subject": subject_ref(ref.subject_id, ref.subject_name),
        "teacher": None if teacher is None else person_ref(teacher),
        "room": room,
        "audience": audience_items(ref),
        "status": ref.status,
        "is_overridden": False,
        "changes": None,
        "topic": ref.topic,
        "has_homework": bool(ref.homework_text),
        "attendance_submitted": False,
    }


async def lesson_items(
    identity: IdentityDirectory, refs: Iterable[LessonRef]
) -> list[JsonObject]:
    """Return `LessonItem` dicts for the lessons, resolving teachers once."""
    lessons = list(refs)
    teachers = await load_users(
        identity, [ref.teacher_id for ref in lessons if ref.teacher_id is not None]
    )
    return [lesson_item(ref, teachers) for ref in lessons]


def homework_item(
    entry: Mapping[str, Any], teachers: Mapping[UUID, UserRef]
) -> JsonObject:
    """Return `HomeworkItem` from a `ClassworkQueries.homework` entry."""
    lesson: LessonRef = entry["lesson"]
    teacher = teachers.get(lesson.teacher_id) if lesson.teacher_id else None
    return {
        "lesson_id": lesson.id,
        "subject": subject_ref(lesson.subject_id, lesson.subject_name),
        "teacher": None if teacher is None else person_ref(teacher),
        "text": lesson.homework_text or "",
        "due_date": lesson.homework_due_date,
        "given_on": lesson.date,
        "updated": False,
        "done_at": entry.get("done_at"),
        "note": entry.get("note"),
    }
