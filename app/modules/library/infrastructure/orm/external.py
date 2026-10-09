"""ORM models of the UniLibrary feed settings (tables only; feeds are not built yet)."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.domain.enums import ExternalSource
from app.modules.library.infrastructure.orm.enum_column import str_enum
from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import Boolean, DateTime, Integer, String, Text, Uuid, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class ExternalFeed(IdMixin, TimestampMixin, Base):
    """A chosen slice of an external catalogue to sync (reserved; no job runs yet)."""

    __tablename__ = "external_feeds"
    __table_args__ = ({"schema": "library"},)

    name: Mapped[str] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(str_enum(ExternalSource, "source"))
    params: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
    enabled: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    max_items: Mapped[int] = mapped_column(Integer, server_default=text("0"))
    estimate: Mapped[int | None] = mapped_column(Integer)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_status: Mapped[str | None] = mapped_column(String(20))
    last_count: Mapped[int | None] = mapped_column(Integer)
    last_error: Mapped[str | None] = mapped_column(Text)


class ExternalFieldMap(TimestampMixin, Base):
    """Maps a lyceum subject to an external catalogue field (reserved)."""

    __tablename__ = "external_field_map"
    __table_args__ = ({"schema": "library"},)

    subject_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    source: Mapped[str] = mapped_column(
        str_enum(ExternalSource, "source"), primary_key=True
    )
    external_field_id: Mapped[int] = mapped_column(Integer, primary_key=True)
