"""Tool results are plain JSON values whatever the use case returns."""

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from uuid import UUID

from app.interfaces.mcp.jsonable import to_jsonable, to_jsonable_dict

from pydantic import BaseModel


class Color(StrEnum):
    RED = "red"


@dataclass(frozen=True, slots=True)
class Inner:
    when: date
    ids: tuple[UUID, ...]


class Model(BaseModel):
    moment: datetime


def test_nested_domain_values_become_json() -> None:
    """Dataclasses, models, UUIDs, dates, enums, sets and decimals."""
    value = {
        "inner": Inner(date(2026, 10, 7), (UUID(int=1),)),
        "model": Model(moment=datetime(2026, 10, 7, 4, 0, tzinfo=UTC)),
        "color": Color.RED,
        "price": Decimal("1.5"),
        "tags": {"a"},
        1: None,
    }

    converted = to_jsonable(value)

    assert converted == {
        "inner": {"when": "2026-10-07", "ids": [str(UUID(int=1))]},
        "model": {"moment": "2026-10-07T04:00:00Z"},
        "color": "red",
        "price": 1.5,
        "tags": ["a"],
        "1": None,
    }
    json.dumps(converted)


def test_unknown_objects_become_strings() -> None:
    """Serialization never fails."""
    assert to_jsonable(object()).startswith("<object")


def test_cycles_stop_at_the_depth_limit() -> None:
    """A self-referencing structure does not recurse forever."""
    loop: list[object] = []
    loop.append(loop)

    json.dumps(to_jsonable(loop))


def test_non_object_results_are_wrapped() -> None:
    """MCP structured output is always an object."""
    assert to_jsonable_dict([1, 2]) == {"result": [1, 2]}
    assert to_jsonable_dict({"a": 1}) == {"a": 1}
