"""Builders of step content blocks in the shape of the API contract (`Block`).

Ids are left empty: the server assigns random ids to blocks, questions, options and
cards (LMS-23).
"""

from typing import Any

from app.interfaces.mcp.cards import FlashcardInput
from app.interfaces.mcp.errors import McpInvalidInputError
from app.interfaces.mcp.lms.inputs import QuestionInput, QuizSettingsInput


def build_text_block(markdown: str) -> dict[str, Any]:
    """Return a text block."""
    return {"id": "", "type": "text", "markdown": markdown}


def build_flashcards_block(cards: list[FlashcardInput]) -> dict[str, Any]:
    """Return a flash cards block (cards belong to the course, not to a student)."""
    return {
        "id": "",
        "type": "flashcards",
        "cards": [{"id": "", "front": c.front, "back": c.back} for c in cards],
    }


def build_test_block(
    settings: QuizSettingsInput | None, questions: list[QuestionInput]
) -> dict[str, Any]:
    """Return a test block with its settings and questions."""
    config = (settings or QuizSettingsInput()).model_dump()
    return {
        "id": "",
        "type": "test",
        "config": config,
        "questions": [build_question(question) for question in questions],
    }


def build_question(question: QuestionInput) -> dict[str, Any]:
    """Validate a question for its type and return it in the API shape."""
    result: dict[str, Any] = {
        "id": "",
        "type": question.type,
        "prompt": question.prompt,
        "points": question.points,
        "explanation": question.explanation,
    }
    if question.type in ("single", "multiple"):
        result["options"] = _options(question)
    elif question.type == "text":
        result["answer"] = _text_answer(question)
    else:
        result["answer"] = _number_answer(question)
    return result


def _options(question: QuestionInput) -> list[dict[str, Any]]:
    options = question.options or []
    if len(options) < 2:
        raise _invalid("a choice question needs at least two options")
    correct = sum(1 for option in options if option.correct)
    if question.type == "single" and correct != 1:
        raise _invalid("a single choice question needs exactly one correct option")
    if question.type == "multiple" and correct < 1:
        raise _invalid("a multiple choice question needs a correct option")
    return [
        {"id": "", "text": o.text, "correct": o.correct, "pinned": o.pinned}
        for o in options
    ]


def _text_answer(question: QuestionInput) -> dict[str, Any]:
    accepted = question.accepted_answers or []
    if not accepted and not question.regex:
        raise _invalid("a text question needs accepted_answers or a regex")
    return {
        "accepted": accepted,
        "regex": question.regex,
        "case_sensitive": question.case_sensitive,
    }


def _number_answer(question: QuestionInput) -> dict[str, Any]:
    if question.number is None:
        raise _invalid("a number question needs the right value in `number`")
    return {"value": question.number, "tolerance": question.tolerance}


def _invalid(reason: str) -> McpInvalidInputError:
    return McpInvalidInputError(params={"reason": reason})
