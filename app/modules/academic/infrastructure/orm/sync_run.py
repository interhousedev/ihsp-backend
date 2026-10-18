"""ORM model of academic.sync_runs."""

from datetime import datetime
from typing import Any

from app.shared.db.base import Base, IdMixin, TimestampMixin

from sqlalchemy import DateTime, Enum, Index, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column


class SyncRun(IdMixin, TimestampMixin, Base):
    """One EMIS sync run; ``stats`` is written by the run's coordinator only."""

    __tablename__ = "sync_runs"
    __table_args__ = (
        Index("ix_sync_runs_started_at", "started_at"),
        {"schema": "academic"},
    )

    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(
        Enum(
            "running",
            "done",
            "failed",
            "stopped",
            "paused",
            name="status",
            native_enum=False,
            create_constraint=True,
        ),
        server_default=text("'running'"),
    )
    stats: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb")
    )
