"""Server-side grading of test attempts (LMS-15, LMS-17).

Grading always uses the content of the revision the student took, never the
current one. Regex answers run with the ``regex`` engine under a time limit.
"""

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

from app.modules.lms.domain.learning.variant import Variant, points_of
from app.modules.lms.domain.step_content import Question, ShowAnswers, TestBlock

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
        correct[question_id] = is_correct(question, answers.get(question_id))
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


def is_correct(question: Question, answer: Answer | None) -> bool:
    """Return True if the answer is fully correct (all or nothing)."""
    if not answer:
        return False
    if question.type in ("single", "multiple"):
        return _choice_correct(question, answer)
    if question.type == "text":
        return _text_correct(question, answer)
    return _number_correct(question, answer)


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
    if question.options is not None:
        order = variant.option_order.get(question.id) or [
            o.id for o in question.options
        ]
        correct = {option.id for option in question.options if option.correct}
        return {
            "option_ids": [option_id for option_id in order if option_id in correct]
        }
    config = question.answer
    if config is None:
        return None
    if question.type == "number":
        return None if config.value is None else {"number": config.value}
    if config.accepted:
        return {"text": config.accepted[0]}
    return None
