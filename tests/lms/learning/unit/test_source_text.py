"""LMS-17: the plain text of a step for notebook sources never holds tests."""

from app.modules.lms.domain.learning.source_text import export_text
from app.modules.lms.domain.step_content import Card, FlashcardsBlock, StepContent
from tests.lms.learning.builders import (
    cards,
    choice,
    content,
    number_question,
    quiz,
    text_block,
    text_question,
)


def test_text_and_flash_card_blocks_are_joined_by_a_blank_line() -> None:
    """Markdown as written; each card is Q/A, cards separated by a blank line."""
    step = content(
        "Cells",
        text_block("t1", "# Cells\n\nThe cell is the unit of life."),
        cards("c1", 2),
        text_block("t2", "Mitochondria make ATP."),
    )

    text, starts = export_text(step)

    assert text == (
        "# Cells\n\nThe cell is the unit of life.\n\n"
        "Q: Front 1\nA: Back 1\n\nQ: Front 2\nA: Back 2\n\n"
        "Mitochondria make ATP."
    )
    assert [text[start:].split("\n")[0] for start in starts] == [
        "# Cells",
        "Q: Front 1",
        "Mitochondria make ATP.",
    ]


def test_block_starts_point_at_the_first_character_of_each_block() -> None:
    """The offsets allow mapping a passage back to its block."""
    step = content("S", text_block("a", "AAA"), text_block("b", "BBBB"), cards("c", 1))

    text, starts = export_text(step)

    assert starts == (0, 5, 11)
    assert text[0:3] == "AAA" and text[5:9] == "BBBB" and text[11:].startswith("Q:")


def test_test_blocks_are_never_exported_with_any_question_type() -> None:
    """LMS-17: prompts, options, correct answers and explanations stay out."""
    block = quiz(
        "quiz",
        [
            choice("q1", correct=["b"], explanation="Secret reason one"),
            choice("q2", correct=["a", "c"], multiple=True),
            text_question("q3", accepted=["hidden-answer"]),
            number_question("q4", value=424242),
        ],
    )

    text, starts = export_text(content("S", text_block("t", "Before."), block))

    assert text == "Before." and starts == (0,)
    for secret in ("Question", "Option", "Secret reason", "hidden-answer", "424242"):
        assert secret not in text


def test_a_step_with_only_tests_has_no_text() -> None:
    """Nothing to export: empty text and no block offsets."""
    assert export_text(content("S", quiz())) == ("", ())


def test_empty_blocks_are_skipped() -> None:
    """Blank Markdown and flash card blocks without cards add nothing."""
    step = StepContent(
        title="S",
        blocks=[
            text_block("a", "  \n"),
            FlashcardsBlock(id="empty", cards=[]),
            text_block("b", "Real text."),
        ],
    )

    assert export_text(step) == ("Real text.", (0,))


def test_card_text_is_trimmed_and_may_span_lines() -> None:
    """Multi-line cards keep their inner line breaks."""
    block = FlashcardsBlock(
        id="c", cards=[Card(id="1", front=" What?\n(two lines) ", back=" Answer ")]
    )

    text, _ = export_text(StepContent(title="S", blocks=[block]))

    assert text == "Q: What?\n(two lines)\nA: Answer"
