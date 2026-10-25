"""ORM model of academic.groups."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    ARRAY,
    Enum,
    Index,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Group(IdMixin, TimestampMixin, Base):
    """A study group such as 2TN2; subgroups are the numbers 1 and 2."""

    __tablename__ = "groups"
    __table_args__ = (
        UniqueConstraint("emis_group_id", name="uq_groups_emis_group_id"),
        Index(
            "ix_groups_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("status = 'active'"),
        ),
        {"schema": "academic"},
    )

    emis_group_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str] = mapped_column(String(64))
    slug: Mapped[str] = mapped_column(String(64))
    current_semester: Mapped[int | None] = mapped_column(SmallInteger)
    emis_curriculum_id: Mapped[int | None] = mapped_column(Integer)
    subject_ids: Mapped[list[UUID]] = mapped_column(
        ARRAY(Uuid), server_default=text("'{}'")
    )
    curator_id: Mapped[UUID | None] = mapped_column(Uuid)
    head_student_id: Mapped[UUID | None] = mapped_column(Uuid)
    status: Mapped[str] = mapped_column(
        Enum(
            "active",
            "archived",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'active'"),
    )
