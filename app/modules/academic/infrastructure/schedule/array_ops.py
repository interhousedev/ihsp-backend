"""PostgreSQL array operators that the generic SQLAlchemy ARRAY type lacks."""

from collections.abc import Sequence
from typing import Any

from sqlalchemy import ARRAY, ColumnElement, Text, literal
from sqlalchemy.orm import InstrumentedAttribute


def overlaps(
    column: InstrumentedAttribute[Any], values: Sequence[str]
) -> ColumnElement[bool]:
    """Return ``column && ARRAY[values]``: the text arrays share an element."""
    operator = column.op("&&", is_comparison=True)
    return operator(literal(list(values), ARRAY(Text)))
