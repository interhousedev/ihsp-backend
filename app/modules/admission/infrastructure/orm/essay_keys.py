"""ORM of the essay data-key ledger: the key generation, its backup and rotation."""

import datetime as dt
from uuid import UUID

from app.modules.admission.infrastructure.orm._common import (
    CreatedMixin,
    S,
    UpdatedMixin,
    check_in,
)
from app.shared.db.base import Base

from sqlalchemy import CheckConstraint, DateTime, Integer, SmallInteger, String, Uuid
from sqlalchemy import text as sql_text
from sqlalchemy.orm import Mapped, mapped_column

ROTATION_STATES = ("idle", "running", "done", "failed")


class EssayKeyStateRow(CreatedMixin, UpdatedMixin, Base):
    """The single row of the key ledger: generation and the last rotation."""

    __tablename__ = "essay_key_state"
    __table_args__ = (
        CheckConstraint("id = 1", name="single_row"),
        check_in("rotation_state", ROTATION_STATES),
        S,
    )

    id: Mapped[int] = mapped_column(SmallInteger, primary_key=True)
    generation: Mapped[int] = mapped_column(Integer, server_default=sql_text("1"))
    rotation_state: Mapped[str] = mapped_column(
        String(8), server_default=sql_text("'idle'")
    )
    rotation_total: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    rotation_done: Mapped[int] = mapped_column(Integer, server_default=sql_text("0"))
    rotation_unreadable: Mapped[int] = mapped_column(
        Integer, server_default=sql_text("0")
    )
    rotation_by: Mapped[UUID | None] = mapped_column(Uuid)
    rotation_started_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rotation_finished_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    rotation_run_id: Mapped[UUID | None] = mapped_column(Uuid)
    """The run that holds the rotation lease; every run step is fenced on it."""
    rotation_heartbeat_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True)
    )
    """Renewed with every step; a run is stale only when this is old."""


class EssayKeyExportRow(Base):
    """The one allowed backup download of a key generation."""

    __tablename__ = "essay_key_exports"
    __table_args__ = (S,)

    generation: Mapped[int] = mapped_column(Integer, primary_key=True)
    exported_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True))
    exported_by: Mapped[UUID] = mapped_column(Uuid)


__all__ = ["EssayKeyExportRow", "EssayKeyStateRow"]
