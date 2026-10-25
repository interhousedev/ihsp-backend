"""The shared lesson SELECT and the mapping of its rows to the Lesson entity."""

from collections.abc import Sequence
from typing import Any, Literal, cast
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.classwork.lesson import Lesson
from app.modules.academic.infrastructure.orm.group import Group
from app.modules.academic.infrastructure.orm.lesson import Lesson as LessonRow
from app.modules.academic.infrastructure.orm.room import Room
from app.modules.academic.infrastructure.orm.subject import Subject
from app.modules.academic.infrastructure.school_days import not_on_saturday
from app.shared.lesson_kind import LessonKind, topic_source_of

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


def lesson_select() -> sa.Select[Any]:
    """SELECT of every lesson column with subject and room names joined in.

    Lessons dated on a Saturday (kept from before the school week was cut) are skipped.
    """
    row = LessonRow
    return (
        sa.select(
            row.id,
            row.term_id,
            row.date,
            row.period,
            row.starts_at,
            row.ends_at,
            row.subject_id,
            Subject.name.label("subject_names"),
            Subject.short_name.label("subject_short"),
            row.teacher_id,
            row.room_id,
            Room.slug.label("room_slug"),
            Room.name.label("room_name"),
            Room.pin.label("room_pin"),
            row.audience,
            row.status,
            row.topic,
            row.is_overridden,
            row.changes,
            row.homework_text,
            row.homework_due_date,
            row.homework_due_auto,
            row.homework_updated_at,
            row.attendance_roster,
            row.attendance_absent,
            row.attendance_excused,
            row.attendance_late,
            row.attendance_version,
            row.attendance_by,
            row.attendance_at,
            row.attendance_source,
            row.kind,
            row.emis_topic,
        )
        .select_from(row)
        .join(Subject, Subject.id == row.subject_id)
        .outerjoin(Room, Room.id == row.room_id)
        .where(not_on_saturday(row.date))
    )


def _names(raw: Any) -> dict[str, str]:
    return {str(k): str(v) for k, v in (raw or {}).items() if v}


def _groups(audience: Sequence[str], names_by_id: dict[UUID, str]) -> dict[UUID, str]:
    ordered = dict.fromkeys(audience_keys.parse(key)[0] for key in audience)
    return {gid: names_by_id[gid] for gid in ordered if gid in names_by_id}


def _to_lesson(row: Any, names_by_id: dict[UUID, str]) -> Lesson:
    audience = tuple(row.audience or ())
    status = cast(Literal["scheduled", "cancelled"], row.status)
    return Lesson(
        id=row.id,
        term_id=row.term_id,
        date=row.date,
        period=row.period,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        subject_id=row.subject_id,
        subject_names=_names(row.subject_names),
        subject_short=row.subject_short,
        teacher_id=row.teacher_id,
        room_id=row.room_id,
        room_slug=row.room_slug,
        room_name=row.room_name,
        room_pin=row.room_pin,
        audience=audience,
        groups=_groups(audience, names_by_id),
        status=status,
        topic=row.topic,
        is_overridden=bool(row.is_overridden),
        changes=row.changes,
        homework_text=row.homework_text,
        homework_due_date=row.homework_due_date,
        homework_due_auto=bool(row.homework_due_auto),
        homework_updated_at=row.homework_updated_at,
        attendance_roster=(
            None if row.attendance_roster is None else tuple(row.attendance_roster)
        ),
        attendance_absent=(
            None if row.attendance_absent is None else tuple(row.attendance_absent)
        ),
        attendance_excused=row.attendance_excused,
        attendance_late=(
            None if row.attendance_late is None else tuple(row.attendance_late)
        ),
        attendance_version=row.attendance_version,
        attendance_by=row.attendance_by,
        attendance_at=row.attendance_at,
        attendance_source=row.attendance_source,
        kind=cast(LessonKind, row.kind),
        topic_source=topic_source_of(row.topic, row.emis_topic),
    )


def lessons_from_rows(
    rows: Sequence[Any], names_by_id: dict[UUID, str]
) -> list[Lesson]:
    """Map rows of ``lesson_select()`` to entities."""
    return [_to_lesson(row, names_by_id) for row in rows]


async def group_name_map(session: AsyncSession, rows: Sequence[Any]) -> dict[UUID, str]:
    """Names of every group mentioned by the audiences of the rows."""
    ids: set[UUID] = set()
    for row in rows:
        ids.update(audience_keys.group_ids(row.audience or ()))
    if not ids:
        return {}
    found = await session.execute(
        sa.select(Group.id, Group.name).where(Group.id.in_(ids))
    )
    return dict(found.tuples().all())


async def fetch_lessons(session: AsyncSession, stmt: sa.Select[Any]) -> list[Lesson]:
    """Run a ``lesson_select()`` based statement and return entities."""
    rows = (await session.execute(stmt)).all()
    return lessons_from_rows(rows, await group_name_map(session, rows))
