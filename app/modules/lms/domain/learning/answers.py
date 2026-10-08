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
    if question.type in ("single", "multiple"):
        return _choice(question, answer)
    if question.type == "text":
        return _text(question, answer)
    return _number(question, answer)


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
