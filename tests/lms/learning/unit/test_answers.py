"""LMS-17: saved answers are checked against the attempt variant."""

from app.modules.lms.domain.learning.answers import normalize_answers
from app.modules.lms.domain.learning.errors import AnswerInvalidError
from app.modules.lms.domain.learning.variant import Variant
from tests.lms.learning.builders import choice, number_question, quiz, text_question

import pytest

TEST = quiz(
    questions=[
        choice("single", correct=["a"]),
        choice("multi", correct=["a", "b"], multiple=True),
        text_question("text", accepted=["x"]),
        number_question("num", value=1),
    ]
)
VARIANT = Variant(("single", "multi", "text", "num"), {})


def test_valid_answers_are_kept_in_their_stored_form() -> None:
    """LMS-17: only the field of the question's type is stored."""
    answers = normalize_answers(
        TEST,
        VARIANT,
        {
            "single": {"option_ids": ["single-a"], "text": "ignored"},
            "multi": {"option_ids": ["multi-a", "multi-b", "multi-a"]},
            "text": {"text": "hello"},
            "num": {"number": 2.5},
        },
    )

    assert answers == {
        "single": {"option_ids": ["single-a"]},
        "multi": {"option_ids": ["multi-a", "multi-b"]},
        "text": {"text": "hello"},
        "num": {"number": 2.5},
    }


@pytest.mark.parametrize(
    "raw",
    [
        {"unknown": {"text": "x"}},
        {"single": {"option_ids": ["single-a", "single-b"]}},
        {"single": {"option_ids": ["multi-a"]}},
        {"single": {"text": "a"}},
        {"multi": {"option_ids": "multi-a"}},
        {"text": {"text": 5}},
        {"text": {"text": "x" * 10_001}},
        {"num": {"number": "5"}},
        {"num": {"number": True}},
        {"num": {"number": float("nan")}},
    ],
)
def test_invalid_answers_are_refused(raw: dict) -> None:
    """LMS-17: nothing outside the variant or of the wrong kind is stored."""
    with pytest.raises(AnswerInvalidError):
        normalize_answers(TEST, VARIANT, raw)


def test_a_question_outside_the_pool_is_refused() -> None:
    """LMS-16: a pool attempt only accepts its own questions."""
    pool = Variant(("single",), {})

    with pytest.raises(AnswerInvalidError):
        normalize_answers(TEST, pool, {"text": {"text": "x"}})
