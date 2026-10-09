"""Rows affected by a DELETE or UPDATE, typed (the async session returns `Result`)."""

from typing import Any, cast

from sqlalchemy import CursorResult, Result


def rows_affected(result: Result[Any]) -> int:
    """How many rows the statement changed."""
    return int(cast("CursorResult[Any]", result).rowcount)
