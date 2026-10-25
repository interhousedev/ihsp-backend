"""Small SQLAlchemy helpers for array operators."""

from collections.abc import Sequence
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.orm import QueryableAttribute
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import TypeEngine

Column = ColumnElement[Any] | QueryableAttribute[Any]

_TEXT_ARRAY: TypeEngine[Any] = sa.ARRAY(sa.Text)
_UUID_ARRAY: TypeEngine[Any] = sa.ARRAY(sa.Uuid)


def text_array(values: Sequence[str]) -> sa.BindParameter[Any]:
    """Bind a list of strings as ``text[]``."""
    return sa.bindparam(None, list(values), type_=_TEXT_ARRAY, unique=True)


def uuid_array(values: Sequence[UUID]) -> sa.BindParameter[Any]:
    """Bind a list of UUIDs as ``uuid[]``."""
    return sa.bindparam(None, list(values), type_=_UUID_ARRAY, unique=True)


def overlaps(column: Column, values: Sequence[str]) -> ColumnElement[bool]:
    """``column && values`` for text arrays."""
    return column.op("&&", is_comparison=True)(text_array(values))


def has_uuid(column: Column, value: UUID) -> ColumnElement[bool]:
    """``column @> ARRAY[value]`` for uuid arrays."""
    return column.op("@>", is_comparison=True)(uuid_array([value]))
