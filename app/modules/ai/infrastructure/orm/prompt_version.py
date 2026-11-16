"""ORM model of ai.prompt_versions (administrators' versions of the prompts)."""

from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, Index, Integer, String, Text, UniqueConstraint, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column


class PromptVersionRow(IdMixin, TimestampMixin, Base):
    """One version of a prompt slot for a locale ("" all); at most one active."""

    __tablename__ = "prompt_versions"
    __table_args__ = (
        UniqueConstraint(
            "task", "name", "locale", "version", name="uq_prompt_versions_slot_version"
        ),
        Index(
            "ux_prompt_versions_active",
            "task",
            "name",
            "locale",
            unique=True,
            postgresql_where=sql_text("active"),
        ),
        Index("ix_prompt_versions_task_version", "task", "version"),
        {"schema": "ai"},
    )

    task: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(64))
    locale: Mapped[str] = mapped_column(String(8), server_default=sql_text("''"))
    version: Mapped[int] = mapped_column(Integer)
    text: Mapped[str] = mapped_column(Text)
    hash: Mapped[str] = mapped_column(String(16))
    active: Mapped[bool] = mapped_column(Boolean, server_default=sql_text("false"))
    created_by: Mapped[UUID | None] = mapped_column(Uuid)
    note: Mapped[str] = mapped_column(String(500), server_default=sql_text("''"))
