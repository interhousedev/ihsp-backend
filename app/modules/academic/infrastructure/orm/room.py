"""ORM model of academic.rooms."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import DateTime, Enum, ForeignKey, String, UniqueConstraint, Uuid, text
from sqlalchemy.orm import Mapped, mapped_column


class Room(IdMixin, TimestampMixin, Base):
    """A room with a public page protected by a PIN."""

    __tablename__ = "rooms"
    __table_args__ = (
        UniqueConstraint("slug", name="uq_rooms_slug"),
        {"schema": "academic"},
    )

    slug: Mapped[str] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(255))
    pin: Mapped[str] = mapped_column(String(16))
    pin_changed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
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
    merged_into_id: Mapped[UUID | None] = mapped_column(
        Uuid, ForeignKey("academic.rooms.id", ondelete="SET NULL")
    )
