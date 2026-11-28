"""LMS Course tool `list_block_types`."""

from typing import Any

from app.interfaces.mcp.toolkit import ToolKit
from app.shared.contracts.lms_blocks import AUTHOR_BLOCK_MODELS
from app.shared.lms_scopes import COURSES_READ

from pydantic import BaseModel

SCOPE = COURSES_READ


def _compact(node: Any) -> Any:  # noqa: ANN401
    """Drop the `title` keywords of a JSON schema; field names stay."""
    if isinstance(node, list):
        return [_compact(item) for item in node]
    if not isinstance(node, dict):
        return node
    result: dict[str, Any] = {}
    for key, value in node.items():
        if key == "title":
            continue
        if key in ("properties", "$defs"):
            result[key] = {name: _compact(sub) for name, sub in value.items()}
        else:
            result[key] = _compact(value)
    return result


def describe_block_type(model: type[BaseModel]) -> dict[str, Any]:
    """Return one block type: description, field schema, an example and notes."""
    schema = _compact(model.model_json_schema())
    description = " ".join((model.__doc__ or "").split())
    schema.pop("description", None)
    catalog: dict[str, Any] = getattr(model, "catalog", {})
    return {
        "type": model.model_fields["type"].default,
        "description": description,
        "schema": schema,
        "example": catalog["examples"][0],
        "notes": catalog.get("notes", ""),
    }


def register(kit: ToolKit) -> None:
    """Register `list_block_types`."""

    @kit.tool(SCOPE)
    async def list_block_types() -> dict[str, Any]:
        """List every kind of block a step can hold, with its fields and an example.

        Call this before add_block, update_block, build_course or update_step: it
        tells which block types exist (text, video, test, flash cards, H5P,
        interactive video, exam, code, HTML widget, AI review, and more), what
        fields each one takes, and what to prepare first (for example a file id).
        Send the block as the `block` argument with its `type` set.
        """
        return {"block_types": [describe_block_type(m) for m in AUTHOR_BLOCK_MODELS]}
