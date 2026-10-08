"""Conversion of use case results into plain JSON-serializable values."""

import dataclasses
from collections.abc import Mapping
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel

_MAX_DEPTH = 12


def to_jsonable(value: Any, _depth: int = 0) -> Any:  # noqa: ANN401 - any input
    """Turn dataclasses, models, UUIDs, dates and collections into JSON values.

    The result holds only dict, list, str, int, float, bool and None. Anything
    unknown becomes its string form so a tool never fails on serialization.
    """
    if _depth > _MAX_DEPTH:
        return str(value)
    if value is None or isinstance(value, bool | int | float | str):
        return value
    depth = _depth + 1
    if isinstance(value, Mapping):
        return {str(key): to_jsonable(item, depth) for key, item in value.items()}
    if isinstance(value, list | tuple | set | frozenset):
        return [to_jsonable(item, depth) for item in value]
    if isinstance(value, BaseModel):
        return to_jsonable(value.model_dump(mode="json"), depth)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return {
            field.name: to_jsonable(getattr(value, field.name), depth)
            for field in dataclasses.fields(value)
        }
    return _scalar(value, depth)


def _scalar(value: Any, depth: int) -> Any:  # noqa: ANN401 - any input
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date):
        return value.isoformat()
    if isinstance(value, Enum):
        return to_jsonable(value.value, depth)
    if isinstance(value, Decimal):
        return float(value)
    return str(value)


def to_jsonable_dict(value: Any) -> dict[str, Any]:  # noqa: ANN401 - any input
    """Convert a tool result; a non-object result is wrapped as {"result": ...}."""
    converted = to_jsonable(value)
    if isinstance(converted, dict):
        return converted
    return {"result": converted}
