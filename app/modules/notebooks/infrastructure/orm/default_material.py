"""ORM model of notebooks.subject_default_materials."""

from uuid import UUID

from app.modules.notebooks.domain.default_materials import (
    DefaultMaterialKind,
    MaterialScope,
)
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    SmallInteger,
    String,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

# Exactly the target that the kind names; the file and the library item are other
# modules' ids (no foreign key), the link is the normalised URL.
SHAPE = (
    "(kind = 'file' AND file_id IS NOT NULL "
    "AND url IS NULL AND library_item_id IS NULL) "
    "OR (kind = 'link' AND url IS NOT NULL "
    "AND file_id IS NULL AND library_item_id IS NULL) "
    "OR (kind = 'library_item' AND library_item_id IS NOT NULL "
    "AND file_id IS NULL AND url IS NULL)"
)


# Who the material is for: all of the subject (admin), the groups of a teacher, or one
# group (and subgroup) of a teacher.
SCOPE_SHAPE = (
    "(scope = 'admin' AND teacher_id IS NULL AND group_id IS NULL "
    "AND subgroup IS NULL) "
    "OR (scope = 'teacher_subject' AND teacher_id IS NOT NULL "
    "AND group_id IS NULL AND subgroup IS NULL) "
    "OR (scope = 'group' AND teacher_id IS NOT NULL AND group_id IS NOT NULL)"
)


class SubjectDefaultMaterial(IdMixin, TimestampMixin, Base):
    """A material every student's subject notebook of an EMIS subject id gets."""

    __tablename__ = "subject_default_materials"
    __table_args__ = (
        Index(
            "ix_subject_default_materials_edu_subject_id_position",
            "edu_subject_id",
            "position",
        ),
        Index(
            "ix_subject_default_materials_teacher_id_edu_subject_id",
            "teacher_id",
            "edu_subject_id",
        ),
        CheckConstraint(SHAPE, name="shape"),
        CheckConstraint(SCOPE_SHAPE, name="scope_shape"),
        {"schema": "notebooks"},
    )

    edu_subject_id: Mapped[int] = mapped_column(Integer)
    kind: Mapped[str] = mapped_column(str_enum(DefaultMaterialKind, "kind"))
    title: Mapped[str] = mapped_column(String(255))
    file_id: Mapped[UUID | None] = mapped_column(Uuid)
    url: Mapped[str | None] = mapped_column(String(2048))
    library_item_id: Mapped[UUID | None] = mapped_column(Uuid)
    position: Mapped[int] = mapped_column(Integer)
    created_by: Mapped[UUID] = mapped_column(Uuid)
    scope: Mapped[str] = mapped_column(
        str_enum(MaterialScope, "scope"), server_default=text("'admin'")
    )
    teacher_id: Mapped[UUID | None] = mapped_column(Uuid)
    group_id: Mapped[UUID | None] = mapped_column(Uuid)
    subgroup: Mapped[int | None] = mapped_column(SmallInteger)
