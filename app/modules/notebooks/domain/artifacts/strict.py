"""JSON schemas for OpenRouter strict structured output (§ 3.4.0, `to_strict_schema`).

Strict mode wants every property required (optional ones become nullable), no
`$ref`s we cannot resolve and `additionalProperties: false` on every object. The
validation keywords it does not support are dropped here and enforced by pydantic
and by the kind's `process()` afterwards.

Anthropic compiles a strict schema only while at most `MAX_UNION_PARAMETERS`
properties are nullable or union-typed; above that every provider answers HTTP 400.
A field marked `json_schema_extra=NOT_NULL` stays optional for pydantic (an edit may
still send null) but is a plain, non-null property in the strict schema, so the model
writes "" or [] when it has nothing.
"""

from typing import Any, Final

from pydantic import BaseModel

MAX_UNION_PARAMETERS: Final = 16
_NOT_NULL_KEY: Final = "x-not-null"
NOT_NULL: Final[dict[str, Any]] = {_NOT_NULL_KEY: True}

_DROPPED = frozenset(
    {
        "default",
        "title",
        "minLength",
        "maxLength",
        "minItems",
        "maxItems",
        "pattern",
        "format",
        "minimum",
        "maximum",
        "exclusiveMinimum",
        "exclusiveMaximum",
        "multipleOf",
        "uniqueItems",
        "examples",
    }
)


def to_strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """Return a self-contained strict JSON schema of a pydantic model."""
    schema = model.model_json_schema()
    definitions: dict[str, Any] = schema.pop("$defs", {})
    inlined = _inline(schema, definitions)
    strict = _strictify(inlined)
    assert isinstance(strict, dict)  # noqa: S101 - a model schema is an object
    return strict


def _inline(node: Any, definitions: dict[str, Any]) -> Any:
    if isinstance(node, list):
        return [_inline(item, definitions) for item in node]
    if not isinstance(node, dict):
        return node
    ref = node.get("$ref")
    if isinstance(ref, str):
        return _inline(definitions[ref.rsplit("/", 1)[-1]], definitions)
    return {key: _inline(value, definitions) for key, value in node.items()}


def _strictify(node: Any) -> Any:
    if isinstance(node, list):
        return [_strictify(item) for item in node]
    if not isinstance(node, dict):
        return node
    cleaned = {
        key: _strict_child(key, value)
        for key, value in node.items()
        if key not in _DROPPED or key == "properties"
    }
    if cleaned.get("type") == "object" and "properties" in cleaned:
        required = set(cleaned.get("required", []))
        properties: dict[str, Any] = cleaned["properties"]
        cleaned["properties"] = {
            name: _property(sub, required=name in required)
            for name, sub in properties.items()
        }
        cleaned["required"] = list(properties)
        cleaned["additionalProperties"] = False
    return cleaned


def _strict_child(key: str, value: Any) -> Any:
    if key == "properties" and isinstance(value, dict):
        return {name: _strictify(sub) for name, sub in value.items()}
    return _strictify(value)


def _property(sub: Any, *, required: bool) -> Any:
    """A required or `NOT_NULL` property as it is, else nullable."""
    if isinstance(sub, dict) and sub.get(_NOT_NULL_KEY):
        plain = {key: value for key, value in sub.items() if key != _NOT_NULL_KEY}
        return _without_null(plain)
    return sub if required else _nullable(sub)


def _without_null(sub: dict[str, Any]) -> dict[str, Any]:
    """Drop the null branch of an `anyOf`; a single branch left replaces it."""
    any_of = sub.get("anyOf")
    if not isinstance(any_of, list):
        return sub
    kept = [x for x in any_of if not (isinstance(x, dict) and x.get("type") == "null")]
    rest = {key: value for key, value in sub.items() if key != "anyOf"}
    if len(kept) == 1 and isinstance(kept[0], dict):
        return {**rest, **kept[0]}
    return {**rest, "anyOf": kept}


def count_unions(schema: Any) -> int:
    """How many nodes of a schema are nullable or union-typed (`anyOf`, type lists)."""
    if isinstance(schema, list):
        return sum(count_unions(item) for item in schema)
    if not isinstance(schema, dict):
        return 0
    own = isinstance(schema.get("type"), list) or "anyOf" in schema or "oneOf" in schema
    return int(own) + sum(count_unions(value) for value in schema.values())


def _nullable(sub: Any) -> Any:
    """Allow null for an optional property."""
    if not isinstance(sub, dict):
        return sub
    any_of = sub.get("anyOf")
    if isinstance(any_of, list):
        if any(isinstance(x, dict) and x.get("type") == "null" for x in any_of):
            return sub
        return {**sub, "anyOf": [*any_of, {"type": "null"}]}
    return {"anyOf": [sub, {"type": "null"}]}
