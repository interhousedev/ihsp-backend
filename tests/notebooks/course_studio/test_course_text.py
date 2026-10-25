"""LMS-AI-STUDIO: text clean-up of the course kinds (labels, headings, titles)."""

from app.modules.notebooks.domain.artifacts.course_text import (
    clean_item_title,
    clean_lesson_markdown,
    demote_headings,
    find_placeholder,
    strip_links_and_images,
    strip_numbering,
    strip_ref_labels,
)

import pytest


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Light is absorbed [S1:P3].", "Light is absorbed."),
        ("Light is absorbed [[S1:P3]].", "Light is absorbed."),
        ("Both stages [S1:P3, S2:P10] matter.", "Both stages matter."),
        ("Both stages (S1:P3) matter.", "Both stages matter."),
        ("A claim ⟦2⟧ with a chip.", "A claim  with a chip."),
        ("See S12:P104 for more", "See for more"),
        ("No labels here: ratio 3:4 and S1.", "No labels here: ratio 3:4 and S1."),
    ],
)
def test_passage_labels_and_chips_never_reach_the_text(raw: str, expected: str) -> None:
    """LMS-AI-STUDIO: students must never see S1:P3 tokens."""
    assert strip_ref_labels(raw) == expected


def test_headings_are_shifted_so_the_shallowest_is_h3() -> None:
    """LMS-AI-STUDIO: the step title is shown above the blocks, so ### is the top."""
    text = "# Title\n\nIntro\n\n## Part\n\ntext\n\n### Deep\n\n#### Deeper"

    assert demote_headings(text) == (
        "### Title\n\nIntro\n\n#### Part\n\ntext\n\n##### Deep\n\n###### Deeper"
    )


def test_headings_that_are_deep_enough_stay_and_levels_stop_at_six() -> None:
    """LMS-AI-STUDIO: no change at ###; never past ######."""
    assert demote_headings("### A\n\n#### B") == "### A\n\n#### B"
    assert demote_headings("# A\n\n###### F") == "### A\n\n###### F"


def test_hash_lines_inside_fenced_code_are_not_headings() -> None:
    """LMS-AI-STUDIO: a shell comment in a code block stays as written."""
    text = "## Run\n\n```sh\n# comment\n```\n"

    assert demote_headings(text) == "### Run\n\n```sh\n# comment\n```\n"


def test_images_go_and_web_links_keep_their_words() -> None:
    """LMS-AI-STUDIO: the model has no URLs, so none are published."""
    text = "![fig](http://x/y.png) Read [the guide](https://x.org/g) now."

    assert strip_links_and_images(text) == " Read the guide now."


def test_lesson_markdown_is_cleaned_in_one_pass() -> None:
    """LMS-AI-STUDIO: labels, HTML, ## headings, blank runs and trailing spaces."""
    raw = (
        "## Photosynthesis [[S1:P1]]  \n\n\n\n<div>Plants turn light into sugar.</div>"
        " (S1:P2)\n\n- point \n"
    )

    assert clean_lesson_markdown(raw) == (
        "### Photosynthesis\n\nPlants turn light into sugar.\n\n- point"
    )


def test_formulas_survive_the_clean_up() -> None:
    """LMS-AI-STUDIO: LaTeX between dollars is kept as written."""
    raw = "### Formula\n\nWe have $6CO_2 + 6H_2O \\to C_6H_{12}O_6$.\n\n$$E = mc^2$$"

    assert clean_lesson_markdown(raw) == raw


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1. Introduction", "Introduction"),
        ("2) Light reactions", "Light reactions"),
        ("2.3 Calvin cycle", "Calvin cycle"),
        ("Lesson 4: Cells", "Cells"),
        ("Step 2 - Cells", "Cells"),
        ("Урок 3. Клетка", "Клетка"),
        ("Dars 5: Hujayra", "Hujayra"),
        ("3 types of triangles", "3 types of triangles"),
        ("2D shapes", "2D shapes"),
        ("1.", "1."),
    ],
)
def test_numbering_is_removed_from_titles_but_not_from_names(
    raw: str, expected: str
) -> None:
    """LMS-AI-STUDIO: the LMS numbers steps itself; a number in a name stays."""
    assert strip_numbering(raw) == expected


def test_item_titles_lose_labels_and_numbering_and_are_cut() -> None:
    """LMS-AI-STUDIO: a one-line title of at most the given length."""
    assert clean_item_title("  1.  Cells   [S1:P1] ") == "Cells"
    assert len(clean_item_title("word " * 100, 20)) <= 20


@pytest.mark.parametrize(
    "text",
    [
        "Add [insert example here] later.",
        "Lorem ipsum dolor",
        "TODO write this",
        "{{ example }}",
        "Use <insert formula> now",
        "[вставьте пример]",
    ],
)
def test_placeholders_are_found(text: str) -> None:
    """LMS-AI-STUDIO: no "[insert ...]" text goes into a course."""
    assert find_placeholder(text) is not None


def test_ordinary_text_has_no_placeholder() -> None:
    """LMS-AI-STUDIO: brackets and the word "add" are fine."""
    assert find_placeholder("Add the numbers [1, 2] and write the sum.") is None
