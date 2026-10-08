"""Turns use case results into the JSON-shaped dicts of the composition ports."""

from collections.abc import Iterable
from typing import cast

from app.interfaces.http.v1.composition.ports import JsonObject

from pydantic_core import to_jsonable_python


def json_object(value: object) -> JsonObject:
    """Return the JSON form of a dict, dataclass or model (UUIDs, dates as text)."""
    return cast(JsonObject, to_jsonable_python(value))


def json_objects(values: Iterable[object]) -> list[JsonObject]:
    """Return the JSON form of each value."""
    return [json_object(value) for value in values]
