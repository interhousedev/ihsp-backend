"""LMS-15, LMS-17: server-side grading of every question type."""

import time
from decimal import Decimal
from typing import Any

from app.modules.lms.domain.learning.grading import (
    build_review,
    grade_attempt,
    is_correct,
    is_passed,
    review_visible,
)
from app.modules.lms.domain.learning.variant import Variant
from app.modules.lms.domain.step_content import Question
from tests.lms.learning.builders import (
    choice,
    number_question,
    quiz,
    text_question,
)

import pytest

Answer = dict[str, Any]


def ids(*letters: str, question: str = "q") -> Answer:
    """An answer choosing options `<question>-<letter>`."""
    return {"option_ids": [f"{question}-{letter}" for letter in letters]}


CASES: list[tuple[str, Question, Answer | None, bool]] = [
    ("single right", choice("q", correct=["a"]), ids("a"), True),
    ("single wrong", choice("q", correct=["a"]), ids("b"), False),
    ("single two options", choice("q", correct=["a"]), ids("a", "b"), False),
    ("single empty", choice("q", correct=["a"]), {"option_ids": []}, False),
    ("single unanswered", choice("q", correct=["a"]), None, False),
    (
        "multiple exact set",
        choice("q", correct=["a", "c"], multiple=True),
        ids("c", "a"),
        True,
    ),
    (
        "multiple missing one",
        choice("q", correct=["a", "c"], multiple=True),
        ids("a"),
        False,
    ),
    (
        "multiple one too many",
        choice("q", correct=["a", "c"], multiple=True),
        ids("a", "b", "c"),
        False,
    ),
    ("text exact", text_question("q", accepted=["Paris"]), {"text": "Paris"}, True),
    (
        "text trimmed and case-insensitive",
        text_question("q", accepted=["Paris"]),
        {"text": "  pARis \n"},
        True,
    ),
    (
        "text any of several",
        text_question("q", accepted=["Paris", "Париж"]),
        {"text": "париж"},
        True,
    ),
    (
        "text case-sensitive wrong case",
        text_question("q", accepted=["Paris"], case_sensitive=True),
        {"text": "paris"},
        False,
    ),
    (
        "text case-sensitive right case",
        text_question("q", accepted=["Paris"], case_sensitive=True),
        {"text": "Paris"},
        True,
    ),
    ("text wrong", text_question("q", accepted=["Paris"]), {"text": "Rome"}, False),
    (
        "text regex full match",
        text_question("q", regex=r"gr[ae]y"),
        {"text": "Grey"},
        True,
    ),
    (
        "text regex must match fully",
        text_question("q", regex=r"gr[ae]y"),
        {"text": "greyhound"},
        False,
    ),
    (
        "text regex case-sensitive",
        text_question("q", regex=r"gr[ae]y", case_sensitive=True),
        {"text": "Grey"},
        False,
    ),
    (
        "text regex is a second way to be right",
        text_question("q", accepted=["colour"], regex=r"colou?r"),
        {"text": "color"},
        True,
    ),
    ("text broken regex", text_question("q", regex="("), {"text": "x"}, False),
    ("text not a string", text_question("q", accepted=["1"]), {"text": 1}, False),
    ("number exact", number_question("q", value=3), {"number": 3}, True),
    ("number off by one", number_question("q", value=3), {"number": 4}, False),
    (
        "number within tolerance",
        number_question("q", value=3, tolerance=0.5),
        {"number": 3.5},
        True,
    ),
    (
        "number outside tolerance",
        number_question("q", value=3, tolerance=0.5),
        {"number": 3.6},
        False,
    ),
    ("number as text is wrong", number_question("q", value=3), {"number": "3"}, False),
    ("number boolean is wrong", number_question("q", value=1), {"number": True}, False),
    (
        "number infinity is wrong",
        number_question("q", value=3, tolerance=1e9),
        {"number": float("inf")},
        False,
    ),
]


@pytest.mark.parametrize(
    ("question", "answer", "expected"),
    [case[1:] for case in CASES],
    ids=[case[0] for case in CASES],
)
def test_a_question_is_graded_all_or_nothing(
    question: Question, answer: Answer | None, expected: bool
) -> None:
    """LMS-15: single, multiple, text and number questions."""
    assert is_correct(question, answer) is expected


def test_a_catastrophic_regex_is_incorrect_and_fast() -> None:
    """LMS-17: a safe regex engine with a time limit."""
    question = text_question("q", regex=r"(a|aa)+$")
    started = time.monotonic()

    correct = is_correct(question, {"text": "a" * 40 + "b"})

    assert correct is False
    assert time.monotonic() - started < 1.0


def test_the_classic_nested_quantifier_regex_is_incorrect_and_fast() -> None:
    """LMS-17: `(a+)+$` on a long string with a wrong tail."""
    question = text_question("q", regex=r"(a+)+$")
    started = time.monotonic()

    correct = is_correct(question, {"text": "a" * 30 + "b"})

    assert correct is False
    assert time.monotonic() - started < 1.0


def test_the_score_is_the_sum_of_the_points_of_the_correct_questions() -> None:
    """LMS-15: points per question."""
    test = quiz(
        questions=[
            choice("q1", correct=["a"], points=2),
            number_question("q2", value=5, points=3),
            text_question("q3", accepted=["x"], points=0.5),
        ]
    )
    variant = Variant(("q1", "q2", "q3"), {"q1": ["q1-a", "q1-b", "q1-c"]})

    grade = grade_attempt(
        test, variant, {"q1": ids("a", question="q1"), "q2": {"number": 6}}
    )

    assert grade.score == Decimal("2")
    assert grade.max_score == Decimal("5.5")
    assert grade.correct == {"q1": True, "q2": False, "q3": False}


def test_only_the_questions_of_the_variant_count() -> None:
    """LMS-16: a pool grades the picked questions only."""
    test = quiz(questions=[choice("q1", correct=["a"]), choice("q2", correct=["a"])])
    variant = Variant(("q2",), {"q2": ["q2-a", "q2-b", "q2-c"]})

    grade = grade_attempt(test, variant, {"q2": ids("a", question="q2")})

    assert (grade.score, grade.max_score) == (Decimal(1), Decimal(1))


@pytest.mark.parametrize(
    ("score", "max_score", "pct", "expected"),
    [
        ("3", "5", 60, True),
        ("2.9", "5", 60, False),
        ("0", "5", 0, True),
        ("5", "5", 100, True),
        ("4.99", "5", 100, False),
        ("0", "0", 100, True),
    ],
)
def test_passing_compares_the_percentage_without_rounding_errors(
    score: str, max_score: str, pct: float, expected: bool
) -> None:
    """LMS-16: `score / max_score * 100 >= passing_score_pct`."""
    assert is_passed(Decimal(score), Decimal(max_score), pct) is expected


@pytest.mark.parametrize(
    ("policy", "passed", "left", "expected"),
    [
        ("never", True, 0, False),
        ("after_submit", False, 2, True),
        ("after_pass", True, 2, True),
        ("after_pass", False, 0, False),
        ("after_last_attempt", True, 1, False),
        ("after_last_attempt", False, 0, True),
        ("after_last_attempt", False, None, False),
    ],
)
def test_show_answers_policies(
    policy: str, passed: bool, left: int | None, expected: bool
) -> None:
    """LMS-16, LMS-17: when correct answers may be shown."""
    shown = review_visible(
        policy,  # type: ignore[arg-type]
        passed=passed,
        attempts_left=left,
    )

    assert shown is expected


def test_the_review_lists_questions_in_variant_order_with_correct_answers() -> None:
    """LMS-17: the review carries correctness, the correct answer and the note."""
    test = quiz(
        questions=[
            choice("q1", correct=["b"]),
            number_question("q2", value=7),
            text_question("q3", accepted=["yes"]),
            text_question("q4", regex=r"\d+"),
        ]
    )
    variant = Variant(("q2", "q1", "q3", "q4"), {"q1": ["q1-c", "q1-b", "q1-a"]})

    review = build_review(test, variant, {"q1": True, "q2": False})

    assert [item["question_id"] for item in review] == ["q2", "q1", "q3", "q4"]
    assert review[0] == {
        "question_id": "q2",
        "correct": False,
        "correct_answer": {"number": 7.0},
        "explanation": "Number explanation.",
    }
    assert review[1]["correct_answer"] == {"option_ids": ["q1-b"]}
    assert review[2]["correct_answer"] == {"text": "yes"}
    assert review[3]["correct_answer"] is None
