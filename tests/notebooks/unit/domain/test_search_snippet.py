"""NB-14: the plain-text snippet of a search hit (§ 3.3 of the AI UX spec)."""

from app.modules.notebooks.domain.search_snippet import (
    SEARCH_SNIPPET_CHARS,
    make_snippet,
)

import pytest

FILLER = "Lorem ipsum dolor sit amet consectetur adipiscing elit sed do eiusmod. "


def test_short_text_is_returned_whole_on_one_line() -> None:
    """NB-14: nothing to cut, no ellipsis."""
    text = "Plants  make\nsugar\tfrom light."

    assert make_snippet(text, "sugar") == "Plants make sugar from light."


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        ("Cells divide ⟦1⟧ by mitosis.", "Cells divide by mitosis."),
        ("Cells divide⟦1,2⟧ by mitosis.", "Cells divide by mitosis."),
        ("Cells divide ⟦w1⟧ by mitosis.", "Cells divide by mitosis."),
        ("Cells divide ⟦w1,3⟧by mitosis.", "Cells divide by mitosis."),
        ("⟦2⟧ Cells divide by mitosis. ⟦w1⟧", "Cells divide by mitosis."),
        (
            "Cells divide by mitosis ⟦1⟧. They grow ⟦w1⟧, then split.",
            "Cells divide by mitosis. They grow, then split.",
        ),
    ],
)
def test_citation_markers_are_removed(raw: str, clean: str) -> None:
    """NB-14: a saved note keeps its chips in the text; the snippet drops them."""
    assert make_snippet(raw, "mitosis") == clean


def test_other_brackets_stay() -> None:
    """NB-14: only citation markers go, not every bracket."""
    assert (
        make_snippet("The set ⟦a⟧ and [1] stay.", "set") == "The set ⟦a⟧ and [1] stay."
    )


def test_long_text_is_cut_around_the_first_match() -> None:
    """NB-14: about 200 characters with the matching word inside."""
    text = FILLER * 20 + "Mitochondria make energy. " + FILLER * 20

    snippet = make_snippet(text, "mitochondria")

    assert "Mitochondria make energy." in snippet
    assert len(snippet) <= SEARCH_SNIPPET_CHARS + 2
    assert snippet.startswith("…") and snippet.endswith("…")


def test_a_match_at_the_start_has_no_leading_ellipsis() -> None:
    """NB-14: the cut is marked only where text was left out."""
    text = "Mitochondria make energy. " + FILLER * 20

    snippet = make_snippet(text, "mitochondria")

    assert snippet.startswith("Mitochondria make energy.")
    assert snippet.endswith("…")
    assert len(snippet) <= SEARCH_SNIPPET_CHARS + 1


def test_a_match_at_the_end_has_no_trailing_ellipsis() -> None:
    """NB-14: the window can end with the text."""
    text = FILLER * 20 + "The cell makes energy in mitochondria."

    snippet = make_snippet(text, "mitochondria")

    assert snippet.startswith("…")
    assert snippet.endswith("energy in mitochondria.")


def test_the_first_match_in_the_text_wins_over_the_order_of_the_words() -> None:
    """NB-14: the window opens at the earliest query word found in the text."""
    text = "Alpha is first. " + FILLER * 20 + "Omega is last."

    snippet = make_snippet(text, "omega alpha")

    assert snippet.startswith("Alpha is first.")


def test_matching_ignores_case() -> None:
    """NB-14: upper and lower case are the same word."""
    text = FILLER * 20 + "ATP is made here. " + FILLER * 20

    assert "ATP is made here." in make_snippet(text, "atp")


def test_another_ending_of_the_word_matches() -> None:
    """NB-14: the database stems words, so the snippet looks for the stem."""
    text = FILLER * 20 + "Фотосинтез идёт на свету. " + FILLER * 20

    assert "Фотосинтез идёт" in make_snippet(text, "фотосинтезе")


def test_uzbek_apostrophes_match_in_any_spelling() -> None:
    """NB-14: o' and oʻ and oʼ are one letter pair for the search."""
    text = FILLER * 20 + "Oʻzbekiston tarixi. " + FILLER * 20

    assert "Oʻzbekiston tarixi." in make_snippet(text, "o'zbekiston")


def test_a_text_without_a_match_starts_at_the_beginning() -> None:
    """NB-14: a hit found by meaning has no word to centre on."""
    text = "Start of the passage. " + FILLER * 20

    snippet = make_snippet(text, "zzzzzz")

    assert snippet.startswith("Start of the passage.")
    assert snippet.endswith("…")


def test_the_cut_never_splits_a_word() -> None:
    """NB-14: both ends of the window sit on word boundaries."""
    text = "word " * 200 + "target " + "word " * 200

    snippet = make_snippet(text, "target")

    words = snippet.strip("…").split()
    assert set(words) <= {"word", "target"}


def test_a_long_text_without_spaces_is_still_cut() -> None:
    """NB-14: no boundary to snap to, so the window is a hard cut."""
    snippet = make_snippet("x" * 1000 + "needle" + "y" * 1000, "needle")

    assert "needle" in snippet
    assert len(snippet) <= SEARCH_SNIPPET_CHARS + 2


def test_markers_do_not_use_up_the_window() -> None:
    """NB-14: the length is counted after the markers are removed."""
    text = "⟦1⟧ " * 100 + "needle " + "word " * 100

    snippet = make_snippet(text, "needle")

    assert "⟦" not in snippet
    assert snippet.startswith("needle")


def test_an_empty_text_gives_an_empty_snippet() -> None:
    """NB-14: nothing in, nothing out."""
    assert make_snippet("  \n ", "needle") == ""
