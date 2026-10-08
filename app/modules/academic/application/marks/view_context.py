"""Builds the JSON-shaped views (SubjectRef, PersonRef, MarkItem, LessonItem)."""

from collections.abc import Collection, Iterable, Mapping
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any
from uuid import UUID

from app.modules.academic.application.marks.ports.repositories import MarksReader
from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.marks.names import localized
from app.modules.academic.domain.marks.read_models import (
    LessonRow,
    MarkRow,
    SubjectInfo,
)
from app.shared.contracts.identity import IdentityDirectory, UserRef


def num(value: Decimal | None) -> float | None:
    """Convert a stored decimal for JSON."""
    return None if value is None else float(value)


@dataclass(frozen=True, slots=True)
class ViewContext:
    """Subjects, people and groups resolved once for a whole response."""

    locale: str
    subjects: Mapping[UUID, SubjectInfo]
    users: Mapping[UUID, UserRef]
    group_names: Mapping[UUID, str] = field(default_factory=dict)

    def subject_ref(self, subject_id: UUID) -> dict[str, Any]:
        """Return `SubjectRef`: the name in the caller's locale, fallback uz, ru, en."""
        info = self.subjects.get(subject_id)
        if info is None:
            return {"id": subject_id, "name": "", "short_name": ""}
        name = localized(info.name, self.locale)
        return {
            "id": subject_id,
            "name": name,
            "short_name": info.short_name or name,
        }

    def subject_name(self, subject_id: UUID) -> str:
        """Return the subject's name in the caller's locale."""
        return str(self.subject_ref(subject_id)["name"])

    def person(self, user_id: UUID | None) -> dict[str, Any] | None:
        """Return `PersonRef` or None for an unknown or missing user."""
        user = None if user_id is None else self.users.get(user_id)
        if user is None:
            return None
        return {
            "id": user.id,
            "first_name": user.first_name,
            "last_name": user.last_name,
        }

    def mark_item(self, row: MarkRow) -> dict[str, Any]:
        """Return `MarkItem`."""
        return {
            "subject": self.subject_ref(row.subject_id),
            "semester": row.semester,
            "type": row.type,
            "value": row.value,
            "date": row.date,
            "lesson_id": row.lesson_id,
        }

    def lesson_item(self, row: LessonRow) -> dict[str, Any]:
        """Return `LessonItem`."""
        room = None
        if row.room_id is not None:
            room = {"id": row.room_id, "slug": row.room_slug, "name": row.room_name}
        return {
            "id": row.id,
            "date": row.date,
            "period": row.period,
            "starts_at": row.starts_at,
            "ends_at": row.ends_at,
            "subject": self.subject_ref(row.subject_id),
            "teacher": self.person(row.teacher_id),
            "room": room,
            "audience": self._audience(row.audience),
            "status": row.status,
            "is_overridden": row.is_overridden,
            "changes": row.changes,
            "topic": row.topic,
            "has_homework": bool(row.homework_text),
            "attendance_submitted": row.attendance_roster is not None,
        }

    def _audience(self, keys: Iterable[str]) -> list[dict[str, Any]]:
        items = []
        for key in keys:
            group_id, subgroup = audience_keys.parse(key)
            items.append(
                {
                    "group_id": group_id,
                    "group_name": self.group_names.get(group_id, ""),
                    "subgroup": subgroup,
                }
            )
        return items


def lesson_group_ids(rows: Iterable[LessonRow]) -> set[UUID]:
    """Return the groups mentioned by the lessons' audience keys."""
    return audience_keys.group_ids(key for row in rows for key in row.audience)


async def build_context(
    reader: MarksReader,
    identity: IdentityDirectory,
    *,
    locale: str,
    subject_ids: Collection[UUID] = (),
    user_ids: Collection[UUID] = (),
    lessons: Iterable[LessonRow] = (),
) -> ViewContext:
    """Load the subjects, people and group names a response needs."""
    rows = list(lessons)
    people = {uid for uid in user_ids if uid is not None}
    people |= {r.teacher_id for r in rows if r.teacher_id is not None}
    subjects = set(subject_ids) | {r.subject_id for r in rows}
    return ViewContext(
        locale=locale,
        subjects=await reader.subjects(subjects) if subjects else {},
        users=await identity.get_users(sorted(people, key=str)) if people else {},
        group_names=await reader.group_names(lesson_group_ids(rows)) if rows else {},
    )


async def caller_locale(identity: IdentityDirectory, user_id: UUID) -> str:
    """Return the caller's locale (ru when the user is unknown)."""
    user = await identity.get_user(user_id)
    return "ru" if user is None else user.locale
