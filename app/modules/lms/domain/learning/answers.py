"""Validation of the answers a student saves for an attempt (LMS-17)."""

import math
from collections.abc import Mapping
from typing import Any, Final

from app.modules.lms.domain.learning.errors import AnswerInvalidError
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.domain.step_content import Question, TestBlock

TEXT_MAX_LENGTH: Final = 10_000


def normalize_answers(
    test: TestBlock, variant: Variant, raw: Mapping[str, Mapping[str, Any]]
) -> dict[str, dict[str, Any]]:
    """Check answers against the attempt and keep only the field of each type.

    Raises:
        AnswerInvalidError: An answer names a question outside the variant, an
            option the question does not have, or a value of the wrong kind.
    """
    by_id = {question.id: question for question in test.questions}
    result: dict[str, dict[str, Any]] = {}
    for question_id, answer in raw.items():
        question = by_id.get(question_id)
        if question is None or question_id not in variant.question_ids:
            raise AnswerInvalidError(params={"question_id": question_id})
        result[question_id] = _normalize_one(question, answer)
    return result


def _normalize_one(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Return the stored form of one answer."""
    if question.type in ("single", "multiple", "sorting"):
        return _choice(question, answer)
    if question.type in ("text", "formula", "free"):
        return _text(question, answer)
    if question.type in ("number", "random_number"):
        return _number(question, answer)
    if question.type == "matching":
        return _pairs(question, answer)
    if question.type == "table":
        return _cells(question, answer)
    if question.type == "blanks":
        return _texts(question, answer)
    return _code(question, answer)


def _choice(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Option ids must belong to the question; single choice takes at most one."""
    ids = answer.get("option_ids")
    known = {option.id for option in question.options or []}
    if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
        raise AnswerInvalidError(params={"question_id": question.id})
    unique = list(dict.fromkeys(ids))
    if not set(unique) <= known or (question.type == "single" and len(unique) > 1):
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"option_ids": unique}


def _text(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Text answers are bounded strings."""
    text = answer.get("text")
    if not isinstance(text, str) or len(text) > TEXT_MAX_LENGTH:
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"text": text}


def _number(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Number answers are finite numbers."""
    value = answer.get("number")
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise AnswerInvalidError(params={"question_id": question.id})
    if not math.isfinite(value):
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"number": value}


def _pairs(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Matching: left pair id -> chosen right pair id, both from the question."""
    given = answer.get("pairs")
    known = {pair.id for pair in question.pairs or []}
    if not isinstance(given, Mapping) or not all(
        k in known and v in known for k, v in given.items()
    ):
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"pairs": {str(k): str(v) for k, v in given.items()}}


def _cells(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Table: marked cells as ``"row:column"`` inside the grid."""
    cells = answer.get("cells")
    table = question.table
    if table is None or not isinstance(cells, list):
        raise AnswerInvalidError(params={"question_id": question.id})
    valid = {
        f"{row}:{column}"
        for row in range(len(table.rows))
        for column in range(len(table.columns))
    }
    if not all(isinstance(cell, str) and cell in valid for cell in cells):
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"cells": list(dict.fromkeys(cells))}


def _texts(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Blanks: one bounded string per blank."""
    texts = answer.get("texts")
    if (
        not isinstance(texts, list)
        or len(texts) != len(question.blanks or [])
        or not all(isinstance(t, str) and len(t) <= TEXT_MAX_LENGTH for t in texts)
    ):
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"texts": list(texts)}


def _code(question: Question, answer: Mapping[str, Any]) -> dict[str, Any]:
    """Code: the source and the output the student reports (both bounded strings)."""
    text = answer.get("text", "")
    output = answer.get("output", "")
    if not isinstance(text, str) or not isinstance(output, str):
        raise AnswerInvalidError(params={"question_id": question.id})
    if len(text) > TEXT_MAX_LENGTH or len(output) > TEXT_MAX_LENGTH:
        raise AnswerInvalidError(params={"question_id": question.id})
    return {"text": text, "output": output}
