"""ORM models of faces.face_profiles, devices, device_calls and passages."""

from datetime import datetime
from uuid import UUID

from app.shared.db.base import Base

from sqlalchemy import Boolean, CheckConstraint, DateTime, Index, String, Uuid, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.types import REAL

SCHEMA = {"schema": "faces"}


class FaceProfileRow(Base):
    """A user's face embedding and the stored photo (a file of the files module)."""

    __tablename__ = "face_profiles"
    __table_args__ = (SCHEMA,)

    user_id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    embedding: Mapped[list[float]] = mapped_column(ARRAY(REAL))
    photo_file_id: Mapped[UUID] = mapped_column(Uuid)
    uploaded_by: Mapped[UUID] = mapped_column(Uuid)
    locked: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DeviceRow(Base):
    """An entrance device; `key_hash` is the SHA-256 of its token."""

    __tablename__ = "devices"
    __table_args__ = (Index("uq_devices_key_hash", "key_hash", unique=True), SCHEMA)

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    name: Mapped[str] = mapped_column(String(80))
    key_prefix: Mapped[str] = mapped_column(String(32))
    key_hash: Mapped[str] = mapped_column(String(64))
    created_by: Mapped[UUID] = mapped_column(Uuid)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class DeviceCallRow(Base):
    """One request from a device (kept 7 days)."""

    __tablename__ = "device_calls"
    __table_args__ = (
        CheckConstraint(
            "status IN ('matched', 'no_match', 'no_face', 'multiple_faces')",
            name="status",
        ),
        Index("ix_device_calls_device_id_at", "device_id", "at"),
        Index("ix_device_calls_at", "at"),
        SCHEMA,
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(16))
    matched_user_id: Mapped[UUID | None] = mapped_column(Uuid)
    excused: Mapped[bool | None] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )


class PassageRow(Base):
    """A recognised student passing the entrance (kept 7 days)."""

    __tablename__ = "passages"
    __table_args__ = (
        CheckConstraint("direction IN ('in', 'out')", name="direction"),
        Index("ix_passages_at", "at"),
        Index("ix_passages_user_id_at", "user_id", "at"),
        SCHEMA,
    )

    id: Mapped[UUID] = mapped_column(Uuid, primary_key=True)
    device_id: Mapped[UUID] = mapped_column(Uuid)
    user_id: Mapped[UUID] = mapped_column(Uuid)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    direction: Mapped[str] = mapped_column(String(3))
    excused: Mapped[bool] = mapped_column(Boolean)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()")
    )
