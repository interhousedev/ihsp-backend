"""Server-side grading of test attempts (LMS-15, LMS-17).

Grading always uses the content of the revision the student took, never the
current one. Regex answers run with the ``regex`` engine under a time limit.
"""

import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from app.modules.lms.domain.learning import expression
from app.modules.lms.domain.learning.variant import Variant, points_of
from app.modules.lms.domain.step_content import (
    Blank,
    Question,
    ShowAnswers,
    TestBlock,
)

import regex  # type: ignore[import-untyped]  # no stubs; see report

REGEX_TIMEOUT_SECONDS: Final = 0.05

Answer = Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class Grade:
    """Result of grading one attempt."""

    correct: dict[str, bool]
    score: Decimal
    max_score: Decimal


def grade_attempt(
    test: TestBlock, variant: Variant, answers: Mapping[str, Answer]
) -> Grade:
    """Grade the saved answers of an attempt against its variant."""
    by_id = {question.id: question for question in test.questions}
    correct: dict[str, bool] = {}
    score = Decimal(0)
    max_score = Decimal(0)
    for question_id in variant.question_ids:
        question = by_id.get(question_id)
        if question is None:
            continue
        points = points_of(question)
        max_score += points
        correct[question_id] = is_correct(
            question, answers.get(question_id), variant.params.get(question_id)
        )
        if correct[question_id]:
            score += points
    return Grade(correct=correct, score=score, max_score=max_score)


def is_passed(score: Decimal, max_score: Decimal, passing_pct: float) -> bool:
    """Return True when ``score / max_score * 100 >= passing_pct``.

    A test without points cannot be failed.
    """
    if max_score <= 0:
        return True
    return score * 100 >= Decimal(str(passing_pct)) * max_score


def review_visible(
    policy: ShowAnswers, *, passed: bool, attempts_left: int | None
) -> bool:
    """Return True when the student may see correct answers (``show_answers``).

    ``attempts_left`` is None when the attempts are unlimited, so the "last
    attempt" never comes.
    """
    if policy == "after_submit":
        return True
    if policy == "after_pass":
        return passed
    if policy == "after_last_attempt":
        return attempts_left is not None and attempts_left <= 0
    return False


# - - - One answer - - -


def is_correct(
    question: Question,
    answer: Answer | None,
    params: Mapping[str, float] | None = None,
) -> bool:
    """Return True if the answer is fully correct (all or nothing).

    ``params`` are the seeded variable values of a generated numeric question.
    Free answers and code without expected outputs are never correct here: a
    reviewer scores them (override).
    """
    if not answer:
        return False
    if question.type == "random_number":
        return _random_correct(question, answer, params or {})
    check = _CORRECTNESS.get(question.type)
    return check is not None and check(question, answer)


def _sorting_correct(question: Question, answer: Answer) -> bool:
    """The items must come in exactly the authored order."""
    chosen = [str(value) for value in answer.get("option_ids") or []]
    return chosen == [option.id for option in question.options or []] != []


def _matching_correct(question: Question, answer: Answer) -> bool:
    """Every left item must point at its own right item."""
    given = answer.get("pairs")
    pairs = question.pairs or []
    if not pairs or not isinstance(given, Mapping):
        return False
    return all(given.get(pair.id) == pair.id for pair in pairs) and len(given) == len(
        pairs
    )


def _table_correct(question: Question, answer: Answer) -> bool:
    """The marked cells (``"row:column"``) must equal the authored ones."""
    table = question.table
    if table is None:
        return False
    expected = {
        f"{row}:{column}"
        for row, line in enumerate(table.correct)
        for column, marked in enumerate(line)
        if marked
    }
    return {str(cell) for cell in answer.get("cells") or []} == expected


def _blanks_correct(question: Question, answer: Answer) -> bool:
    """Every blank must hold one of its accepted answers (or match its regex)."""
    blanks = question.blanks or []
    texts = answer.get("texts")
    if not blanks or not isinstance(texts, list) or len(texts) != len(blanks):
        return False
    return all(
        isinstance(text, str) and _blank_matches(blank, text.strip())
        for blank, text in zip(blanks, texts, strict=True)
    )


def _blank_matches(blank: Blank, value: str) -> bool:
    """Match one blank like a text answer."""
    if any(
        _same_text(value, accepted.strip(), blank.case_sensitive)
        for accepted in blank.accepted
    ):
        return True
    return blank.regex is not None and _regex_matches(
        blank.regex, value, case_sensitive=blank.case_sensitive
    )


def _random_correct(
    question: Question, answer: Answer, params: Mapping[str, float]
) -> bool:
    """Compare the number with the formula evaluated at the attempt's values."""
    spec = question.random
    value = answer.get("number")
    if spec is None or isinstance(value, bool) or not isinstance(value, int | float):
        return False
    try:
        expected = expression.evaluate(spec.formula, params)
    except expression.ExpressionError:
        return False
    return math.isfinite(value) and abs(value - expected) <= max(spec.tolerance, 1e-9)


def _formula_correct(question: Question, answer: Answer) -> bool:
    """Compare the student's expression with the author's at sample points."""
    spec = question.formula
    text = answer.get("text")
    if spec is None or not isinstance(text, str) or not spec.expression.strip():
        return False
    return expression.equivalent(
        spec.expression,
        text,
        spec.variables,
        tolerance=spec.tolerance,
        seed=question.id,
        symbolic=spec.mode == "symbolic",
    )


def normalize_output(text: str) -> str:
    """Compare program outputs ignoring line endings and trailing spaces."""
    lines = [line.rstrip() for line in text.replace("\r\n", "\n").split("\n")]
    return "\n".join(lines).strip()


def _code_correct(question: Question, answer: Answer) -> bool:
    """Compare the reported output with the expected ones; no outputs = manual."""
    spec = question.code
    output = answer.get("output")
    if spec is None or not spec.expected_outputs or not isinstance(output, str):
        return False
    given = normalize_output(output)
    return any(given == normalize_output(item) for item in spec.expected_outputs)


def _choice_correct(question: Question, answer: Answer) -> bool:
    """Compare the chosen option ids with the correct ones as sets."""
    chosen = {str(value) for value in answer.get("option_ids") or []}
    expected = {option.id for option in question.options or [] if option.correct}
    return bool(chosen) and chosen == expected


def _text_correct(question: Question, answer: Answer) -> bool:
    """Match the trimmed text against the accepted answers or the regex."""
    config = question.answer
    text = answer.get("text")
    if config is None or not isinstance(text, str):
        return False
    value = text.strip()
    for accepted in config.accepted or []:
        if _same_text(value, accepted.strip(), config.case_sensitive):
            return True
    return config.regex is not None and _regex_matches(
        config.regex, value, case_sensitive=config.case_sensitive
    )


def _same_text(left: str, right: str, case_sensitive: bool) -> bool:
    """Compare two strings, ignoring case unless the question is case sensitive."""
    if case_sensitive:
        return left == right
    return left.casefold() == right.casefold()


def _regex_matches(pattern: str, value: str, *, case_sensitive: bool) -> bool:
    """Full-match with a time limit; a timeout or a broken pattern is incorrect."""
    flags = 0 if case_sensitive else regex.IGNORECASE
    try:
        return (
            regex.fullmatch(pattern, value, flags=flags, timeout=REGEX_TIMEOUT_SECONDS)
            is not None
        )
    except (TimeoutError, regex.error):
        return False


def _number_correct(question: Question, answer: Answer) -> bool:
    """Accept a number within the question's tolerance."""
    config = question.answer
    value = answer.get("number")
    if config is None or config.value is None:
        return False
    if isinstance(value, bool) or not isinstance(value, int | float):
        return False
    if not math.isfinite(value):
        return False
    return abs(value - config.value) <= config.tolerance


# Kinds judged from the answer alone; random_number also needs the seeded params.
_CORRECTNESS: Final[dict[str, Callable[[Question, Answer], bool]]] = {
    "single": _choice_correct,
    "multiple": _choice_correct,
    "text": _text_correct,
    "number": _number_correct,
    "sorting": _sorting_correct,
    "matching": _matching_correct,
    "table": _table_correct,
    "blanks": _blanks_correct,
    "formula": _formula_correct,
    "code": _code_correct,
}


# - - - Review (answers shown after grading) - - -


def build_review(
    test: TestBlock, variant: Variant, correct: Mapping[str, bool]
) -> list[dict[str, Any]]:
    """Return per-question review items in variant order, with answers and notes."""
    by_id = {question.id: question for question in test.questions}
    items: list[dict[str, Any]] = []
    for question_id in variant.question_ids:
        question = by_id.get(question_id)
        if question is None:
            continue
        items.append(
            {
                "question_id": question_id,
                "correct": correct.get(question_id, False),
                "correct_answer": correct_answer_of(question, variant),
                "explanation": question.explanation,
            }
        )
    return items


def correct_answer_of(question: Question, variant: Variant) -> dict[str, Any] | None:
    """Return the correct answer in the shape of ``Answer``, if it is one value."""
    if _has_own_shape(question):
        return _OWN_SHAPE[question.type](question, variant)
    if question.options is not None:
        return _option_answer(question, variant)
    return _single_value_answer(question)


def _has_own_shape(question: Question) -> bool:
    """Return True when the kind has its own answer shape and the data it needs."""
    kind = question.type
    if kind in ("sorting", "matching", "blanks"):
        return True
    if kind == "table":
        return question.table is not None
    if kind == "formula":
        return question.formula is not None
    if kind == "random_number":
        return question.random is not None
    if kind == "code":
        return bool(question.code and question.code.expected_outputs)
    return False


def _sorting_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The authored order of the options."""
    return {"option_ids": [option.id for option in question.options or []]}


def _matching_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """Each left item paired with its own right item."""
    return {"pairs": {pair.id: pair.id for pair in question.pairs or []}}


def _table_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The marked cells as ``"row:column"``."""
    table = question.table
    if table is None:
        return None
    return {
        "cells": [
            f"{row}:{column}"
            for row, line in enumerate(table.correct)
            for column, marked in enumerate(line)
            if marked
        ]
    }


def _blanks_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The first accepted answer of each blank (empty when none is set)."""
    return {
        "texts": [
            blank.accepted[0] if blank.accepted else ""
            for blank in question.blanks or []
        ]
    }


def _formula_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The author's expression."""
    formula = question.formula
    if formula is None:
        return None
    return {"text": formula.expression}


def _random_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The formula at the variant's values; None when it cannot be computed."""
    spec = question.random
    if spec is None:
        return None
    try:
        return {
            "number": expression.evaluate(
                spec.formula, variant.params.get(question.id, {})
            )
        }
    except expression.ExpressionError:
        return None


def _code_shape(question: Question, variant: Variant) -> dict[str, Any] | None:
    """The first expected output."""
    spec = question.code
    if not spec or not spec.expected_outputs:
        return None
    return {"output": spec.expected_outputs[0]}


def _option_answer(question: Question, variant: Variant) -> dict[str, Any]:
    """The correct option ids, in the order the student saw them."""
    options = question.options or []
    order = variant.option_order.get(question.id) or [option.id for option in options]
    correct = {option.id for option in options if option.correct}
    return {"option_ids": [option_id for option_id in order if option_id in correct]}


def _single_value_answer(question: Question) -> dict[str, Any] | None:
    """The one value of a text or number question, from its ``answer`` config."""
    config = question.answer
    if config is None:
        return None
    if question.type == "number":
        return None if config.value is None else {"number": config.value}
    if config.accepted:
        return {"text": config.accepted[0]}
    return None


# Answer shapes of the kinds that ``_has_own_shape`` accepts.
_OWN_SHAPE: Final[dict[str, Callable[[Question, Variant], dict[str, Any] | None]]] = {
    "sorting": _sorting_shape,
    "matching": _matching_shape,
    "table": _table_shape,
    "blanks": _blanks_shape,
    "formula": _formula_shape,
    "random_number": _random_shape,
    "code": _code_shape,
}
