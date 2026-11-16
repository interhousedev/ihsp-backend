"""The test catalog and the students' test and certificate entries."""

from datetime import date, datetime
from typing import Any
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base, IdMixin

from sqlalchemy import (
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Uuid,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

_STATUSES = ("planned", "registered", "taken", "score_received")


class ScoreTestRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """An administrator-editable kind of test or certificate."""

    __tablename__ = "test_catalog"
    __table_args__ = (S,)

    key: Mapped[str] = mapped_column(String(40), unique=True)
    names: Mapped[dict[str, str]] = mapped_column(JSONB)
    sections: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB, server_default=text("'[]'::jsonb")
    )
    total: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    total_mode: Mapped[str] = mapped_column(String(10))
    superscore: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    needs_label: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    needs_level: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    position: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    active: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))


class ScoreEntryRow(IdMixin, CreatedMixin, UpdatedMixin, Base):
    """A student's planned or taken test, or a certificate."""

    __tablename__ = "test_scores"
    __table_args__ = (check_in("status", _STATUSES), S)

    student_id: Mapped[UUID] = mapped_column(Uuid, index=True)
    test_id: Mapped[UUID] = mapped_column(
        ForeignKey("admission.test_catalog.id", ondelete="RESTRICT")
    )
    status: Mapped[str] = mapped_column(String(14))
    test_date: Mapped[date | None] = mapped_column(Date)
    registration_deadline: Mapped[date | None] = mapped_column(Date)
    label: Mapped[str | None] = mapped_column(String(120))
    level: Mapped[str | None] = mapped_column(String(60))
    sections: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    total: Mapped[Any | None] = mapped_column(JSONB)
    certificate_document_id: Mapped[UUID | None] = mapped_column(
        ForeignKey("admission.documents.id", ondelete="SET NULL")
    )
    verification_url: Mapped[str | None] = mapped_column(String(500))
    send_note: Mapped[str | None] = mapped_column(String(500))
    is_official: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    verified_by: Mapped[UUID | None] = mapped_column(Uuid)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
