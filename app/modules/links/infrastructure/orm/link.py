"""ORM model of links.links."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    BigInteger,
    CheckConstraint,
    DateTime,
    Enum,
    Index,
    Integer,
    String,
    Text,
    Uuid,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column


class Link(IdMixin, TimestampMixin, Base):
    """A public pointer: short link, share of a chat or card set, lesson resource."""

    __tablename__ = "links"
    __table_args__ = (
        CheckConstraint("(kind = 'url') = (target_url IS NOT NULL)", name="url_target"),
        CheckConstraint("(kind = 'file') = (file_id IS NOT NULL)", name="file_target"),
        CheckConstraint(
            "(kind IN ('chat', 'flashcard_set', 'artifact')) = (target_id IS NOT NULL)",
            name="share_target",
        ),
        CheckConstraint(
            "lesson_id IS NULL OR kind IN ('url', 'file')", name="lesson_kind"
        ),
        CheckConstraint(
            "(lesson_id IS NULL) = (lesson_role IS NULL)", name="lesson_role_pair"
        ),
        CheckConstraint("share_mode IS NULL OR kind = 'chat'", name="share_mode_chat"),
        Index(
            "ix_links_slug_active",
            "slug",
            unique=True,
            postgresql_where=text("slug_released_at IS NULL"),
        ),
        Index("ix_links_owner_id_kind", "owner_id", "kind"),
        Index("ix_links_kind_target_id", "kind", "target_id"),
        Index("ix_links_file_id", "file_id"),
        Index(
            "ix_links_lesson_id",
            "lesson_id",
            postgresql_where=text("lesson_id IS NOT NULL"),
        ),
        {"schema": "links"},
    )

    slug: Mapped[str] = mapped_column(String(100))
    kind: Mapped[str] = mapped_column(
        Enum(
            "url",
            "file",
            "chat",
            "flashcard_set",
            "artifact",
            name="kind",
            native_enum=False,
            create_constraint=True,
        )
    )
    owner_id: Mapped[UUID] = mapped_column(Uuid)
    target_url: Mapped[str | None] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text)
    file_id: Mapped[UUID | None] = mapped_column(Uuid)
    target_id: Mapped[UUID | None] = mapped_column(Uuid)
    title: Mapped[str | None] = mapped_column(String(500))
    lesson_id: Mapped[UUID | None] = mapped_column(Uuid)
    lesson_role: Mapped[str | None] = mapped_column(
        Enum(
            "material",
            "attachment",
            "homework",
            name="lesson_role",
            native_enum=False,
            create_constraint=True,
        )
    )
    share_mode: Mapped[str | None] = mapped_column(
        Enum(
            "snapshot",
            "live",
            name="share_mode",
            native_enum=False,
            create_constraint=True,
        )
    )
    snapshot_seq: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hits: Mapped[int] = mapped_column(BigInteger, server_default=text("0"))
    last_hit_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    hidden_by: Mapped[UUID | None] = mapped_column(Uuid)
    disabled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    disabled_by: Mapped[UUID | None] = mapped_column(Uuid)
    disabled_reason: Mapped[str | None] = mapped_column(String(500))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reports: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    last_reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reports_reviewed_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    slug_released_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
