from app.modules.admission.domain.essay_text import (
    Paragraph,
    Transition,
    is_scene_break,
    paragraphs,
    split_blocks,
)

import pytest


@pytest.mark.parametrize(
    "line",
    [
        "* * *",
        "***",
        "---",
        "___",
        "###",
        "~~~",
        "•••",
        "* * * *",
        "— — —",
        "§",
        " ... ",
    ],
)
def test_scene_breaks(line: str) -> None:
    assert is_scene_break(line)


@pytest.mark.parametrize(
    "line", ["", "   ", "Hello", "- item", "1.", "* * * * * * * * * * *"]
)
def test_not_scene_breaks(line: str) -> None:
    assert not is_scene_break(line)


def test_blank_line_split_matches_old_rule() -> None:
    assert paragraphs("  One two\n\n\nThree\n \nFour\n") == ["One two", "Three", "Four"]
    assert paragraphs("  \n\n ") == []


def test_break_without_blank_lines_splits() -> None:
    assert split_blocks("One\n* * *\nTwo\nlines") == [
        Paragraph("One"),
        Transition("* * *"),
        Paragraph("Two\nlines"),
    ]


def test_breaks_are_not_counted() -> None:
    assert paragraphs("One\n\n***\n\nTwo\n---\n---\nThree") == ["One", "Two", "Three"]
