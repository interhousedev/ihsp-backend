"""ORM model of academic.students."""

from datetime import date, datetime
from uuid import UUID

from app.shared.db.base import Base, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Student(TimestampMixin, Base):
    """Academic data of a student; the primary key is the identity user id.

    Names live on the identity user; there is no foreign key across schemas.
    """

    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("calendar_token_hash", name="uq_students_calendar_token_hash"),
        CheckConstraint("subgroup IN (1, 2)", name="subgroup"),
        Index("ix_students_group_id_status", "group_id", "status"),
        {"schema": "academic"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    group_id: Mapped[UUID] = mapped_column(Uuid, ForeignKey("academic.groups.id"))
    subgroup: Mapped[int | None] = mapped_column(SmallInteger)
    subgroup_set_by: Mapped[UUID | None] = mapped_column(Uuid)
    subgroup_set_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "left",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'active'"),
    )
    left_at: Mapped[date | None] = mapped_column(Date)
    left_reason: Mapped[str | None] = mapped_column(
        Enum(
            "graduated",
            "expelled",
            "transferred",
            "other",
            name="left_reason",
            native_enum=False,
            create_constraint=True,
        )
    )
    calendar_token_hash: Mapped[str | None] = mapped_column(String(64))
    backfilled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    profile_synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    sync_failures: Mapped[int] = mapped_column(SmallInteger, server_default=text("0"))
    sync_error: Mapped[str | None] = mapped_column(Text)
