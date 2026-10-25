"""LMS-14: points of tests as learners see them in the sidebar and the lesson header."""

from decimal import Decimal

from app.modules.lms.domain.learning.points import (
    block_max_points,
    earned_points,
    sum_points,
)
from tests.lms.learning.builders import choice, number_question, quiz, text_question

import pytest


def test_a_test_is_worth_the_points_of_all_its_questions() -> None:
    """No pool: every question counts."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["a"], points=1),
            number_question("q2", value=4, points=2.5),
            text_question("q3", accepted=["yes"], points=0.5),
        ],
    )

    assert block_max_points(block) == Decimal("4.0")


def test_a_pool_is_worth_its_best_questions() -> None:
    """A random pool of 2 questions: a perfect attempt can never beat the total."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["a"], points=1),
            number_question("q2", value=4, points=3),
            text_question("q3", accepted=["yes"], points=2),
        ],
        pool_size=2,
    )

    assert block_max_points(block) == Decimal(5)


def test_a_pool_larger_than_the_test_counts_every_question() -> None:
    """The render also clamps ``pool_size`` to the number of questions."""
    block = quiz("quiz", [choice("q1", correct=["a"], points=2)], pool_size=5)

    assert block_max_points(block) == Decimal(2)


def test_decimal_points_are_exact() -> None:
    """0.1 + 0.2 stays 0.3, so the sidebar never shows 0.30000000000000004."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["a"], points=0.1),
            number_question("q2", value=4, points=0.2),
        ],
    )

    assert block_max_points(block) == Decimal("0.3")


@pytest.mark.parametrize(
    ("best", "expected"),
    [
        (None, 0),
        (Decimal(-1), 0),
        (Decimal(2), 2),
        (Decimal(3), 3),
        (Decimal(7), 3),
    ],
)
def test_earned_points_stay_between_zero_and_the_total(
    best: Decimal | None, expected: int
) -> None:
    """A shrunk test caps an older, higher score; nothing is negative."""
    assert earned_points(best, Decimal(3)) == Decimal(expected)


def test_sum_of_nothing_is_zero() -> None:
    assert sum_points([]) == Decimal(0)
