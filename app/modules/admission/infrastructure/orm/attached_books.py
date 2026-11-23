"""Library books a staff member recommends to a student."""

from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column

__all__ = ["AttachedBookRow"]


class AttachedBookRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """One library book attached to a student's courses.

    `item_id` is not a FK: the library module owns the item and may retire it.
    """

    __tablename__ = "attached_books"
    __table_args__ = (
        Index("uq_attached_books_student_item", "student_id", "item_id", unique=True),
        max_len("note", 300),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    item_id: Mapped[UUID] = mapped_column(Uuid)
    attached_by: Mapped[UUID] = mapped_column(Uuid)
    note: Mapped[str | None] = mapped_column(String(300))
