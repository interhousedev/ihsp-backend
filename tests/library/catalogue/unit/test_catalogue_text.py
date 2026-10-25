"""LIB-13: pages of extracted text, the `no_text` rule and the duplicate hash."""

from app.modules.library.domain.catalogue_text import (
    chunk_text,
    content_hash,
    split_pages,
    text_status_for,
)
from app.modules.library.domain.enums import TextStatus


def test_pages_are_cut_at_the_given_offsets() -> None:
    """LIB-13: the files module gives where each page starts."""
    text = "one\ntwo\nthree\n"

    assert split_pages(text, (0, 4, 8)) == ["one", "two", "three"]


def test_text_without_offsets_becomes_virtual_pages_at_paragraph_ends() -> None:
    """LIB-13: Markdown and text files have no pages; paragraphs stay whole."""
    paragraphs = ["a" * 30, "b" * 30, "c" * 30]
    text = "\n\n".join(paragraphs)

    pages = split_pages(text, ())

    assert pages == [text]
    assert chunk_text(text, size=70) == ["a" * 30 + "\n\n" + "b" * 30, "c" * 30]


def test_a_paragraph_longer_than_a_page_is_cut_at_a_space() -> None:
    """LIB-13: no word is cut in half when a space is near."""
    text = " ".join(["word"] * 20)

    pieces = chunk_text(text, size=30)

    assert all(len(piece) <= 30 for piece in pieces)
    assert " ".join(pieces).split() == ["word"] * 20


def test_unbroken_text_is_cut_hard() -> None:
    """LIB-13: a string without spaces is still split."""
    assert chunk_text("x" * 25, size=10) == ["x" * 10, "x" * 10, "x" * 5]


def test_empty_text_has_no_pages() -> None:
    """LIB-13: nothing to index."""
    assert chunk_text("  \n\n ") == []


def test_ten_pages_with_199_characters_are_a_scan() -> None:
    """LIB-13: under 200 characters per 10 pages means no_text."""
    assert text_status_for(199, 10) is TextStatus.NO_TEXT
    assert text_status_for(200, 10) is TextStatus.READY


def test_threshold_scales_with_the_page_count() -> None:
    """LIB-13: 300 pages need 6000 characters."""
    assert text_status_for(5_999, 300) is TextStatus.NO_TEXT
    assert text_status_for(6_000, 300) is TextStatus.READY


def test_hash_ignores_whitespace_case_and_uzbek_script() -> None:
    """LIB-13: the same text in Latin or Cyrillic Uzbek is a duplicate."""
    latin = content_hash("O'zbek   adabiyoti\n", "uz")
    cyrillic = content_hash("Ўзбек адабиёти", "uz")

    assert latin == cyrillic
    assert content_hash("other text", "uz") != latin
