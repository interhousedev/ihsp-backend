"""Small SQLAlchemy helpers for PostgreSQL array operators."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement

Column = ColumnElement[Any] | QueryableAttribute[Any]


def overlaps(column: Column, values: Sequence[str]) -> ColumnElement[bool]:
    """``column && values`` for a ``text[]`` column."""
    bound = sa.bindparam(None, list(values), type_=sa.ARRAY(sa.Text), unique=True)
    return column.op("&&", is_comparison=True)(bound)


def has_uuid(column: Column, value: UUID) -> ColumnElement[bool]:
    """``column @> ARRAY[value]`` for a ``uuid[]`` column."""
    bound = sa.bindparam(None, [value], type_=sa.ARRAY(sa.Uuid), unique=True)
    return column.op("@>", is_comparison=True)(bound)
