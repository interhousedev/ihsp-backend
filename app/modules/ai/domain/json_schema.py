"""Strict, self-contained JSON schemas for tool parameters."""

from typing import Any

from pydantic import BaseModel

_SCHEMA_LISTS = ("anyOf", "allOf", "oneOf", "prefixItems")
_SCHEMA_VALUES = ("items", "additionalProperties", "not")


def tool_parameters(model: type[BaseModel]) -> dict[str, Any]:
    """Return the model's JSON schema with `$ref`s inlined and titles removed."""
    schema = model.model_json_schema()
    definitions: dict[str, Any] = schema.pop("$defs", {})
    schema.pop("description", None)  # the model class docstring is not for the LLM
    return _clean(_inline(schema, definitions))  # type: ignore[no-any-return]


def _inline(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_inline(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        target = definitions[ref.rsplit("/", 1)[-1]]
        return _inline(target, definitions)
    return {key: _inline(value, definitions) for key, value in node.items()}


def _clean(node: Any) -> Any:
    """Drop `title` keys of schema nodes (not properties called "title")."""
    if not isinstance(node, dict):
        return node
    cleaned: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title" and isinstance(value, str):
            continue
        cleaned[key] = _clean_child(key, value)
    return cleaned


def _clean_child(key: str, value: Any) -> Any:
    if key == "properties" and isinstance(value, dict):
        return {name: _clean(sub) for name, sub in value.items()}
    if key in _SCHEMA_LISTS and isinstance(value, list):
        return [_clean(sub) for sub in value]
    if key in _SCHEMA_VALUES:
        return _clean(value)
    return value
