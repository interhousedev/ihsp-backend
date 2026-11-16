"""Fake model answers generated from a JSON schema (admission and other schemas)."""

from typing import Any

_TEXT = "Sample answer written by the fake model."


def document_for(schema: dict[str, Any]) -> Any:
    """Return a minimal document valid against `schema`."""
    return _value(schema, schema.get("$defs", {}), 0)


def _resolve(node: dict[str, Any], defs: dict[str, Any]) -> dict[str, Any]:
    ref = node.get("$ref")
    if isinstance(ref, str):
        return _resolve(defs[ref.rsplit("/", 1)[-1]], defs)
    return node


def _value(node: dict[str, Any], defs: dict[str, Any], depth: int) -> Any:
    node = _resolve(node, defs)
    if "const" in node:
        return node["const"]
    if "enum" in node:
        return node["enum"][0]
    for key in ("anyOf", "oneOf"):
        if key in node:
            options = [o for o in node[key] if _resolve(o, defs).get("type") != "null"]
            return _value(options[0], defs, depth) if options else None
    kind = node.get("type")
    if isinstance(kind, list):
        kind = next((k for k in kind if k != "null"), "null")
    if kind == "object":
        return {
            name: _value(sub, defs, depth + 1)
            for name, sub in node.get("properties", {}).items()
        }
    if kind == "array":
        return [
            _value(node.get("items", {}), defs, depth + 1)
            for _ in range(_array_count(node, depth))
        ]
    return _scalar(kind, node)


def _array_count(node: dict[str, Any], depth: int) -> int:
    count = int(node.get("minItems", 0))
    if depth < 4:
        count = max(count, 1)
    return min(count, int(node.get("maxItems", count)))


def _scalar(kind: Any, node: dict[str, Any]) -> Any:
    if kind == "string":
        return _string(node)
    if kind == "integer":
        low = max(int(node.get("minimum", 0)), 0)
        return min(low, int(node.get("maximum", low)))
    if kind == "number":
        return float(max(node.get("minimum", 0), 0))
    if kind == "boolean":
        return False
    return None


def _string(node: dict[str, Any]) -> str:
    text = _TEXT
    low = int(node.get("minLength", 0))
    while len(text) < low:
        text += " " + _TEXT
    high = node.get("maxLength")
    return text[: int(high)] if high is not None else text
