"""SQLAlchemy type of pgvector's `halfvec(N)` without the `pgvector` package.

A value travels as the text `[0.1,0.2,...]` and is cast on the server side, so the
driver needs no codec: asyncpg sends a string for a parameter of an unknown type and
returns a string for a column of one. The same text format is what `psql` shows.

`halfvec` stores each number in 2 bytes (IEEE half precision) instead of 4: half the
disk and index size, and a cosine ranking that differs from `vector` only in the 4th
decimal. The HNSW index supports up to 4000 dimensions of `halfvec` (2000 of `vector`).
"""

from collections.abc import Callable, Sequence
from typing import Any

from sqlalchemy import cast
from sqlalchemy.dialects.postgresql.base import ischema_names
from sqlalchemy.engine import Dialect
from sqlalchemy.sql.elements import ColumnElement
from sqlalchemy.types import UserDefinedType


def to_text(values: Sequence[float]) -> str:
    """The pgvector text form of a vector: `[0.1,0.2]`."""
    return "[" + ",".join(format(float(v), ".7g") for v in values) + "]"


def from_text(text: str) -> list[float]:
    """Parse the text form back into floats."""
    body = text.strip().removeprefix("[").removesuffix("]")
    return [float(part) for part in body.split(",")] if body else []


class HalfVec(UserDefinedType[list[float]]):
    """`halfvec(dims)`: a vector of half-precision numbers (pgvector 0.7+)."""

    cache_ok = True

    def __init__(self, dims: int | None = None) -> None:
        """`dims` is the fixed size; None leaves the column untyped."""
        self.dims = dims

    def get_col_spec(self, **kw: Any) -> str:
        """The DDL name: `HALFVEC(1024)`."""
        return "HALFVEC" if self.dims is None else f"HALFVEC({self.dims})"

    def bind_processor(
        self, dialect: Dialect
    ) -> Callable[[Sequence[float] | str | None], str | None]:
        """Send the text form (a str passes through unchanged)."""

        def process(value: Sequence[float] | str | None) -> str | None:
            if value is None or isinstance(value, str):
                return value
            return to_text(value)

        return process

    def bind_expression(self, bindvalue: Any) -> ColumnElement[Any]:
        """Cast the text parameter to `halfvec(N)` on the server."""
        return cast(bindvalue, self)

    def result_processor(
        self, dialect: Dialect, coltype: object
    ) -> Callable[[str | None], list[float] | None]:
        """Read the text form into a list of floats."""

        def process(value: str | None) -> list[float] | None:
            return None if value is None else from_text(value)

        return process


# `inspector.get_columns` then returns HalfVec instead of warning about the type.
ischema_names["halfvec"] = HalfVec
