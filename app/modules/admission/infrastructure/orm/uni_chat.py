"""University chats: links to AI chats, default prompts, the web research cache."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
    max_len,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    String,
    Text,
    UniqueConstraint,
    Uuid,
)
from sqlalchemy import text as sql_text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class UniChatRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """The AI chat of one student about one university."""

    __tablename__ = "uni_chats"
    __table_args__ = (
        UniqueConstraint("student_id", "institution_id"),
        S,
    )

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    institution_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.institutions.id", ondelete="CASCADE"), index=True
    )
    chat_id: Mapped[UUID] = mapped_column(Uuid, unique=True)
    auto_run_pending: Mapped[bool] = mapped_column(
        Boolean, server_default=sql_text("false")
    )
    auto_ran_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class UniDefaultPromptRow(CreatedMixin, UpdatedMixin, Base):
    """The prompt a student's university chats run once on the first open."""

    __tablename__ = "uni_default_prompts"
    __table_args__ = (max_len("prompt", 2000), S)

    student_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    prompt: Mapped[str] = mapped_column(Text)


class UniWebCacheRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A research search or fetched page, reused while younger than 14 days."""

    __tablename__ = "uni_web_cache"
    __table_args__ = (
        check_in("kind", ("search", "page", "advice")),
        UniqueConstraint("kind", "cache_key"),
        S,
    )

    kind: Mapped[str] = mapped_column(String(6))
    cache_key: Mapped[str] = mapped_column(String(64))
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB)
