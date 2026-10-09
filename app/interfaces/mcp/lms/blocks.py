"""Builders of step content blocks in the shape of the API contract (`Block`).

The builders live in ``app.shared.contracts.lms_blocks`` (the course author assistant
uses them too); here a broken question becomes the MCP input error. Ids are left
empty: the server assigns random ids to blocks, questions, options and cards (LMS-23).
"""

from typing import Any

from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.lms.inputs import QuestionInput, QuizSettingsInput
from app.shared.contracts import lms_blocks
from app.shared.contracts.lms_blocks import (
    BlockInputError,
    FlashcardInput,
    build_text_block,
)

__all__ = [
    "build_flashcards_block",
    "build_question",
    "build_test_block",
    "build_text_block",
]


def build_flashcards_block(cards: list[FlashcardInput]) -> dict[str, Any]:
    """Return a flash cards block (cards belong to the course, not to a student)."""
    return lms_blocks.build_flashcards_block(cards)


def build_test_block(
    settings: QuizSettingsInput | None, questions: list[QuestionInput]
) -> dict[str, Any]:
    """Return a test block with its settings and questions."""
    try:
        return lms_blocks.build_test_block(settings, questions)
    except BlockInputError as error:
        raise McpInvalidInputError(params={"reason": str(error)}) from error


def build_question(question: QuestionInput) -> dict[str, Any]:
    """Validate a question for its type and return it in the API shape."""
    try:
        return lms_blocks.build_question(question)
    except BlockInputError as error:
        raise McpInvalidInputError(params={"reason": str(error)}) from error
