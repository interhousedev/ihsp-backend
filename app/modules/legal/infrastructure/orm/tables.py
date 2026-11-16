"""ORM models of legal.documents and legal.acceptances."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

KINDS = (
    "privacy",
    "terms",
    "biometric",
    "ai",
    "admission_privacy",
    "admission_terms",
    "admission_disclaimer",
)
STATUSES = ("draft", "published")


def in_values(column: str, values: tuple[str, ...]) -> str:
    """SQL of a CHECK that the column holds one of the values."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class LegalDocumentRow(IdMixin, TimestampMixin, Base):
    """One version of a document; texts are jsonb objects keyed uz, ru, en."""

    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(in_values("kind", KINDS), name="kind"),
        CheckConstraint(in_values("status", STATUSES), name="status"),
        UniqueConstraint(
            "kind", "app_scope", "version", name="uq_documents_kind_scope_version"
        ),
        Index(
            "uq_documents_one_draft_per_kind_scope",
            "kind",
            "app_scope",
            unique=True,
            postgresql_where=text("status = 'draft'"),
        ),
        {"schema": "legal"},
    )

    kind: Mapped[str] = mapped_column(String(32))
    app_scope: Mapped[str] = mapped_column(
        String(32), server_default="global", default="global"
    )
    version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(16))
    title: Mapped[dict[str, Any]] = mapped_column(JSONB)
    body_markdown: Mapped[dict[str, Any]] = mapped_column(JSONB)
    announcement: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[UUID | None] = mapped_column(Uuid)


class AcceptanceRow(IdMixin, TimestampMixin, Base):
    """A user accepted a version of a kind. Rows are inserted, never updated."""

    __tablename__ = "acceptances"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "kind",
            "app_scope",
            "version",
            name="uq_acceptances_user_kind_scope_version",
        ),
        Index("ix_acceptances_kind_scope_version", "kind", "app_scope", "version"),
        {"schema": "legal"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    kind: Mapped[str] = mapped_column(String(32))
    app_scope: Mapped[str] = mapped_column(
        String(32), server_default="global", default="global"
    )
    version: Mapped[int] = mapped_column(Integer)
    guardian_attested: Mapped[bool] = mapped_column(
        server_default=text("false"), default=False
    )
    accepted_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    ip: Mapped[str | None] = mapped_column(Text)
    user_agent: Mapped[str | None] = mapped_column(Text)


class PurposeConsentRow(IdMixin, TimestampMixin, Base):
    """A subject's answer to one admission purpose; one row per user and purpose."""

    __tablename__ = "purpose_consents"
    __table_args__ = (
        UniqueConstraint("user_id", "purpose", name="uq_purpose_consents_user"),
        CheckConstraint(in_values("method", ("app", "guardian")), name="method"),
        {"schema": "legal"},
    )

    user_id: Mapped[UUID] = mapped_column(Uuid)
    purpose: Mapped[str] = mapped_column(String(32))
    method: Mapped[str] = mapped_column(String(10), server_default="app")
    given_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    version: Mapped[int] = mapped_column(Integer, server_default="1")
