"""Building LessonView read models from joined rows."""

import datetime as dt
from collections.abc import Iterable, Sequence
from typing import Any, cast
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys
from app.modules.academic.domain.schedule.audience_display import display_names
from app.modules.academic.domain.schedule.generation import PlannedLesson
from app.modules.academic.domain.schedule.lesson_view import LessonView
from app.modules.academic.domain.schedule.subject import subject_name
from app.modules.academic.infrastructure.orm import Group as GroupRow
from app.modules.academic.infrastructure.orm import Lesson as LessonRow
from app.modules.academic.infrastructure.orm import Room as RoomRow
from app.modules.academic.infrastructure.orm import Subject as SubjectRow
from app.modules.academic.infrastructure.schedule.mappers import subject_to_entity
from app.shared.contracts.academic import LessonRef
from app.shared.lesson_kind import topic_source_of

from sqlalchemy import Row, Select, select
from sqlalchemy.ext.asyncio import AsyncSession


def lesson_select() -> Select[tuple[LessonRow, SubjectRow, RoomRow]]:
    """Return a select of lessons joined with subjects and (optional) rooms."""
    return (
        select(LessonRow, SubjectRow, RoomRow)
        .join(SubjectRow, SubjectRow.id == LessonRow.subject_id)
        .outerjoin(RoomRow, RoomRow.id == LessonRow.room_id)
    )


async def group_names_for(
    session: AsyncSession, audiences: Iterable[Sequence[str]]
) -> dict[UUID, str]:
    """Return {group_id: name} for every group mentioned in the audiences."""
    ids = {gid for keys in audiences for gid in audience_keys.group_ids(keys)}
    if not ids:
        return {}
    rows = await session.execute(
        select(GroupRow.id, GroupRow.name).where(GroupRow.id.in_(list(ids)))
    )
    return {row.id: row.name for row in rows}


def _ref(
    row: LessonRow,
    subject: SubjectRow,
    room: RoomRow | None,
    names: dict[UUID, str],
    locale: str,
) -> LessonRef:
    keys = tuple(row.audience or [])
    return LessonRef(
        id=row.id,
        date=row.date,
        period=row.period,
        starts_at=row.starts_at,
        ends_at=row.ends_at,
        subject_id=row.subject_id,
        subject_name=subject_name(subject_to_entity(subject), locale),
        teacher_id=row.teacher_id,
        room_id=row.room_id,
        room_slug=room.slug if room else None,
        room_name=room.name if room else None,
        audience=keys,
        group_names=display_names(keys, names),
        status=cast(Any, row.status),
        topic=row.topic,
        homework_text=row.homework_text,
        homework_due_date=row.homework_due_date,
        kind=cast(Any, row.kind),
        topic_source=topic_source_of(row.topic, row.emis_topic),
    )


async def build_views(
    session: AsyncSession, rows: Sequence[Row[Any]], locale: str
) -> list[LessonView]:
    """Turn joined rows into views, loading group names in one query."""
    names = await group_names_for(session, (row.audience or [] for row, _, _ in rows))
    views: list[LessonView] = []
    for row, subject, room in rows:
        keys = row.audience or []
        views.append(
            LessonView(
                ref=_ref(row, subject, room, names, locale),
                subject_short=subject.short_name,
                is_overridden=bool(row.is_overridden),
                changes=dict(row.changes) if row.changes else None,
                attendance_submitted=row.attendance_absent is not None,
                term_id=row.term_id,
                audience_groups={
                    gid: names[gid]
                    for gid in audience_keys.group_ids(keys)
                    if gid in names
                },
            )
        )
    return views


def projected_view(
    planned: PlannedLesson,
    *,
    lesson_id: UUID,
    day: dt.date,
    subject: SubjectRow,
    room: RoomRow | None,
    names: dict[UUID, str],
    locale: str,
) -> LessonView:
    """Build a view for a lesson projected from a timetable entry."""
    keys = planned.audience
    ref = LessonRef(
        id=lesson_id,
        date=day,
        period=planned.period,
        starts_at=planned.starts_at,
        ends_at=planned.ends_at,
        subject_id=planned.subject_id,
        subject_name=subject_name(subject_to_entity(subject), locale),
        teacher_id=planned.teacher_id,
        room_id=planned.room_id,
        room_slug=room.slug if room else None,
        room_name=room.name if room else None,
        audience=keys,
        group_names=display_names(keys, names),
        status="scheduled",
        topic=None,
        homework_text=None,
        homework_due_date=None,
    )
    return LessonView(
        ref=ref,
        subject_short=subject.short_name,
        is_overridden=False,
        changes=None,
        attendance_submitted=False,
        term_id=planned.term_id,
        audience_groups={
            gid: names[gid] for gid in audience_keys.group_ids(keys) if gid in names
        },
    )
