"""A small check of a structured-output answer against the schema that was asked for."""

from typing import Any

_TYPES: dict[str, tuple[type, ...]] = {
    "object": (dict,),
    "array": (list,),
    "string": (str,),
    "integer": (int,),
    "number": (int, float),
    "boolean": (bool,),
    "null": (type(None),),
}


def _type_ok(kinds: Any, value: Any) -> bool:
    names = kinds if isinstance(kinds, list) else [kinds]
    for name in names:
        accepted = _TYPES.get(name)
        if accepted is None:
            return True
        if isinstance(value, bool) and bool not in accepted:
            continue
        if isinstance(value, accepted):
            return True
    return False


def schema_violation(schema: dict[str, Any], value: Any, path: str = "$") -> str | None:
    """Return where `value` breaks `schema` (None when it fits).

    Covers what strict structured output promises: types, enums, required
    properties, no extra properties, array items and `anyOf`. A node it cannot
    read (`$ref`, unknown keywords) is accepted.
    """
    if "$ref" in schema:
        return None
    options = schema.get("anyOf")
    if isinstance(options, list):
        if any(schema_violation(option, value, path) is None for option in options):
            return None
        return f"{path}: no anyOf branch fits"
    if "type" in schema and not _type_ok(schema["type"], value):
        return f"{path}: expected {schema['type']}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: not in enum"
    if isinstance(value, dict):
        return _object_violation(schema, value, path)
    if isinstance(value, list):
        return _items_violation(schema, value, path)
    return None


def _items_violation(schema: dict[str, Any], value: list[Any], path: str) -> str | None:
    items = schema.get("items")
    if not isinstance(items, dict):
        return None
    for index, item in enumerate(value):
        found = schema_violation(items, item, f"{path}[{index}]")
        if found is not None:
            return found
    return None


def _object_violation(
    schema: dict[str, Any], value: dict[str, Any], path: str
) -> str | None:
    properties = schema.get("properties", {})
    missing = [n for n in schema.get("required", []) if n not in value]
    if missing:
        return f"{path}.{missing[0]}: missing"
    if schema.get("additionalProperties") is False:
        extra = [n for n in value if n not in properties]
        if extra:
            return f"{path}.{extra[0]}: unexpected"
    for name, child in properties.items():
        if name in value and isinstance(child, dict):
            found = schema_violation(child, value[name], f"{path}.{name}")
            if found is not None:
                return found
    return None
