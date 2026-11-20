"""A small JSON Schema validator for the arguments of an AI request.

Supports what request schemas use: `type`, `properties`, `required`,
`additionalProperties: false`, `enum`, `items`, string length and numeric bounds.
It returns the problems as `path: reason` lines; an empty list means valid.
"""

from collections.abc import Mapping
from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "array": (list, tuple),
    "object": (dict,),
}


def _is(value: Any, name: str) -> bool:
    if name in ("integer", "number") and isinstance(value, bool):
        return False
    return isinstance(value, _TYPES.get(name, (object,)))


def validate_args(schema: Mapping[str, Any], args: Mapping[str, Any]) -> list[str]:
    """The problems of `args` against an object `schema` (empty: valid)."""
    problems: list[str] = []
    _check(schema, dict(args), "", problems)
    return problems


def _check(schema: Mapping[str, Any], value: Any, path: str, out: list[str]) -> None:
    where = path or "arguments"
    kind = schema.get("type")
    if isinstance(kind, str) and not _is(value, kind):
        out.append(f"{where}: expected {kind}")
        return
    if "enum" in schema and value not in schema["enum"]:
        out.append(f"{where}: not one of {list(schema['enum'])}")
    if isinstance(value, str):
        _check_string(schema, value, where, out)
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        _check_number(schema, value, where, out)
    if isinstance(value, dict):
        _check_object(schema, value, path, out)
    if isinstance(value, (list, tuple)) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            _check(schema["items"], item, f"{path}[{index}]", out)


def _check_number(
    schema: Mapping[str, Any], value: float, where: str, out: list[str]
) -> None:
    if "minimum" in schema and value < schema["minimum"]:
        out.append(f"{where}: below minimum {schema['minimum']}")
    if "maximum" in schema and value > schema["maximum"]:
        out.append(f"{where}: above maximum {schema['maximum']}")


def _check_string(
    schema: Mapping[str, Any], value: str, where: str, out: list[str]
) -> None:
    if "maxLength" in schema and len(value) > schema["maxLength"]:
        out.append(f"{where}: longer than {schema['maxLength']}")
    if "minLength" in schema and len(value) < schema["minLength"]:
        out.append(f"{where}: shorter than {schema['minLength']}")


def _check_object(
    schema: Mapping[str, Any], value: dict[str, Any], path: str, out: list[str]
) -> None:
    properties: Mapping[str, Any] = schema.get("properties") or {}
    prefix = f"{path}." if path else ""
    for name in schema.get("required") or ():
        if name not in value:
            out.append(f"{prefix}{name}: required")
    for name, item in value.items():
        sub = properties.get(name)
        if sub is None:
            if schema.get("additionalProperties") is False:
                out.append(f"{prefix}{name}: not allowed")
            continue
        _check(sub, item, f"{prefix}{name}", out)
