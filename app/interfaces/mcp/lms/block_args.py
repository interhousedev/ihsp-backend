"""Convert block arguments of LMS tools to the LMS shape, with fixable errors."""

from typing import Any

from app.shared.contracts.lms_blocks import (
    BlockInput,
    BlockInputError,
    QuestionInput,
    build_block,
    build_question,
)

from mcp.server.fastmcp.exceptions import ToolError


def block_dict(block: BlockInput) -> dict[str, Any]:
    """Return the block in the LMS shape.

    Raises:
        ToolError: A rule is broken; the text says which one.
    """
    try:
        return build_block(block)
    except BlockInputError as exc:
        raise ToolError(f"Invalid block: {exc}. Fix it and call again.") from exc


def question_dict(question: QuestionInput) -> dict[str, Any]:
    """Return the question in the LMS shape.

    Raises:
        ToolError: A rule is broken; the text says which one.
    """
    try:
        return build_question(question)
    except BlockInputError as exc:
        raise ToolError(f"Invalid question: {exc}. Fix it and call again.") from exc
