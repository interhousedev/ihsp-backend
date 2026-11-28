"""ORM model of academic.day_blocks (lunch, second lunch, breaks, assemblies)."""

import datetime as dt
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    CheckConstraint,
    Enum,
    SmallInteger,
    String,
    Time,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class DayBlock(IdMixin, TimestampMixin, Base):
    """A non-lesson block of the school day for some weekdays and some groups."""

    __tablename__ = "day_blocks"
    __table_args__ = (
        CheckConstraint("ends_at > starts_at", name="time_order"),
        CheckConstraint(
            "cardinality(weekdays) > 0 AND weekdays <@ ARRAY[1,2,3,4,5]::smallint[]",
            name="weekdays",
        ),
        CheckConstraint(
            "(scope = 'course') = (course IS NOT NULL)", name="course_scope"
        ),
        CheckConstraint(
            "scope <> 'groups' OR cardinality(group_ids) > 0", name="groups_scope"
        ),
        {"schema": "academic"},
    )

    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(
        Enum(
            "lunch",
            "second_lunch",
            "break",
            "assembly",
            "other",
            name="kind",
            native_enum=False,
            create_constraint=True,
        )
    )
    starts_at: Mapped[dt.time] = mapped_column(Time)
    ends_at: Mapped[dt.time] = mapped_column(Time)
    weekdays: Mapped[list[int]] = mapped_column(ARRAY(SmallInteger))
    scope: Mapped[str] = mapped_column(
        Enum(
            "all",
            "course",
            "groups",
            name="scope",
            native_enum=False,
            create_constraint=True,
        )
    )
    group_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), default=list, server_default=text("'{}'")
    )
    course: Mapped[int | None] = mapped_column(SmallInteger)
