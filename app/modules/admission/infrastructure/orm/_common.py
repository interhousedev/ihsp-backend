"""Shared column helpers of the admission ORM."""

from collections.abc import Iterable
from datetime import datetime
from typing import Final

from sqlalchemy import CheckConstraint, DateTime, Integer, func, text
from sqlalchemy.orm import Mapped, mapped_column

SCHEMA: Final = "admission"
S: Final = {"schema": SCHEMA}


def in_values(column: str, values: Iterable[str]) -> str:
    """SQL of a CHECK that the column holds one of the values."""
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


def check_in(column: str, values: Iterable[str]) -> CheckConstraint:
    """A CHECK constraint named after the column."""
    return CheckConstraint(in_values(column, values), name=column)


def max_len(column: str, limit: int) -> CheckConstraint:
    """A CHECK on `char_length(column) <= limit`."""
    return CheckConstraint(f"char_length({column}) <= {limit}", name=f"{column}_length")


class LockMixin:
    """Optimistic lock counter (PATCH bodies carry it; mismatch → 409)."""

    lock_version: Mapped[int] = mapped_column(Integer, server_default=text("0"))


class CreatedMixin:
    """created_at set by the database."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )


class UpdatedMixin:
    """updated_at maintained on every update."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
