"""Convert block arguments of LMS tools to the LMS shape, with fixable errors."""

from typing import Any, Final

from app.interfaces.mcp.errors import McpInvalidInputError
from app.shared.contracts.lms_blocks import (
    AuthorBlockInput,
    BlockInputError,
    QuestionInput,
    build_block,
    build_question,
)

from mcp.server.fastmcp.exceptions import ToolError
from pydantic import TypeAdapter, ValidationError

_BLOCK: Final[TypeAdapter[Any]] = TypeAdapter(AuthorBlockInput)
_MAX_REPORTED: Final = 5


def block_dict(block: AuthorBlockInput) -> dict[str, Any]:
    """Return the block in the LMS shape.

    Raises:
        ToolError: A rule is broken; the text says which one.
    """
    try:
        return build_block(block)
    except BlockInputError as exc:
        raise ToolError(f"Invalid block: {exc}. Fix it and call again.") from exc


def parse_block(raw: dict[str, Any]) -> dict[str, Any]:
    """Validate a block a client sent as JSON and return it in the LMS shape.

    The shape of every type comes from ``list_block_types``.

    Raises:
        McpInvalidInputError: A field is wrong; the reason names its path.
    """
    try:
        block = _BLOCK.validate_python(raw)
    except ValidationError as exc:
        errors = exc.errors(include_url=False)
        shown = [
            f"{'.'.join(str(part) for part in e['loc']) or 'block'}: {e['msg']}"
            for e in errors[:_MAX_REPORTED]
        ]
        raise McpInvalidInputError(
            params={"reason": "; ".join(shown) + ". See list_block_types."}
        ) from exc
    try:
        return build_block(block)
    except BlockInputError as exc:
        raise McpInvalidInputError(params={"reason": str(exc)}) from exc


def question_dict(question: QuestionInput) -> dict[str, Any]:
    """Return the question in the LMS shape.

    Raises:
        ToolError: A rule is broken; the text says which one.
    """
    try:
        return build_question(question)
    except BlockInputError as exc:
        raise ToolError(f"Invalid question: {exc}. Fix it and call again.") from exc
