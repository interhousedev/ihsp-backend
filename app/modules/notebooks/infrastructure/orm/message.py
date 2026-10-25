"""ORM model of notebooks.messages."""

from typing import Any
from uuid import UUID

from app.modules.notebooks.domain.enums import MessageRole
from app.modules.notebooks.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    SmallInteger,
    String,
    UniqueConstraint,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class Message(IdMixin, TimestampMixin, Base):
    """One message of the notebook chat (one thread per notebook and user)."""

    __tablename__ = "messages"
    __table_args__ = (
        UniqueConstraint(
            "notebook_id", "user_id", "seq", name="uq_messages_notebook_id_user_id_seq"
        ),
        {"schema": "notebooks"},
    )

    notebook_id: Mapped[UUID] = mapped_column(
        Uuid, ForeignKey("notebooks.notebooks.id", ondelete="CASCADE")
    )
    user_id: Mapped[UUID] = mapped_column(Uuid)
    seq: Mapped[int] = mapped_column(Integer)
    role: Mapped[str] = mapped_column(str_enum(MessageRole, "role"))
    content: Mapped[dict[str, Any]] = mapped_column(JSONB)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    tokens_cached: Mapped[int | None] = mapped_column(Integer)
    weighted: Mapped[int | None] = mapped_column(Integer)
    model: Mapped[str | None] = mapped_column(String(100))
    feedback: Mapped[int | None] = mapped_column(SmallInteger)
    stopped: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
