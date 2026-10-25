"""Declarative base and common columns."""

from datetime import datetime
from typing import Any
from uuid import UUID

from app.shared.ids import new_id

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

NAMING = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    """Base class of every ORM model."""

    metadata = MetaData(naming_convention=NAMING)
    # Safe defaults: every datetime is timestamptz, every dict is jsonb.
    type_annotation_map = {
        datetime: DateTime(timezone=True),
        dict[str, Any]: JSONB,
    }


class IdMixin:
    """UUIDv7 primary key."""

    id: Mapped[UUID] = mapped_column(primary_key=True, default=new_id)


class TimestampMixin:
    """created_at / updated_at maintained by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
