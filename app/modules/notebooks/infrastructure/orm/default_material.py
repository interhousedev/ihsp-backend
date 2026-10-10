"""ORM model of notebooks.subject_default_materials."""

from uuid import UUID

from app.modules.notebooks.domain.default_materials import DefaultMaterialKind
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import CheckConstraint, Index, Integer, String, Uuid
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


class SubjectDefaultMaterial(IdMixin, TimestampMixin, Base):
    """A material every student's subject notebook of an EMIS subject id gets."""

    __tablename__ = "subject_default_materials"
    __table_args__ = (
        Index(
            "ix_subject_default_materials_edu_subject_id_position",
            "edu_subject_id",
            "position",
        ),
        CheckConstraint(SHAPE, name="shape"),
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
