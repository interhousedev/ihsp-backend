"""FILE-7: the assistant reads text in pages of up to 8 KB."""

from app.modules.files.domain.errors import TextPageNotFoundError
from app.modules.files.domain.text_pages import PAGE_BYTES, get_page, split_pages

import pytest
from hypothesis import given
from hypothesis import strategies as st


def test_short_text_is_one_page() -> None:
    """Text under the limit is not split."""
    assert split_pages("hello world") == ["hello world"]


def test_empty_text_is_one_empty_page() -> None:
    """There is always at least one page."""
    assert split_pages("") == [""]


def test_pages_are_at_most_8_kb_and_split_on_whitespace() -> None:
    """Pages end after the last whitespace before the limit."""
    words = ["word%04d" % i for i in range(5000)]
    text = " ".join(words)

    pages = split_pages(text)

    assert len(pages) > 1
    assert all(len(page.encode()) <= PAGE_BYTES for page in pages)
    assert "".join(pages) == text
    for page in pages[:-1]:
        assert page.endswith(" ")
    assert all(not page.startswith(" ") for page in pages)


def test_a_word_is_never_cut_when_whitespace_is_available() -> None:
    """Every page boundary falls between words."""
    text = " ".join(["abcdefghij"] * 3000)

    pages = split_pages(text)

    rejoined_words = "".join(pages).split(" ")
    assert set(rejoined_words) == {"abcdefghij"}
    for page in pages:
        assert set(page.split()) == {"abcdefghij"}


def test_text_without_whitespace_is_cut_at_a_character_boundary() -> None:
    """Cyrillic text without spaces: no page ends inside a UTF-8 sequence."""
    text = "щ" * 10000

    pages = split_pages(text)

    assert all(len(page.encode()) <= PAGE_BYTES for page in pages)
    assert "".join(pages) == text
    assert len(pages) == 3


def test_newlines_and_tabs_count_as_whitespace() -> None:
    """Splits may happen at any ASCII whitespace."""
    text = "\n".join(["line of text"] * 2000)

    pages = split_pages(text)

    assert all(page.endswith("\n") for page in pages[:-1])
    assert "".join(pages) == text


def test_get_page_is_one_based_and_rejects_out_of_range() -> None:
    """Page 0 and pages past the end are NotFound."""
    pages = ["a", "b"]

    assert get_page(pages, 1) == "a"
    assert get_page(pages, 2) == "b"
    for bad in (0, 3, -1):
        with pytest.raises(TextPageNotFoundError):
            get_page(pages, bad)


@given(st.text(max_size=3000), st.integers(min_value=8, max_value=200))
def test_pages_always_join_back_into_the_text(text: str, limit: int) -> None:
    """Property: splitting loses nothing and respects the byte limit."""
    pages = split_pages(text, limit)

    assert "".join(pages) == text
    assert all(len(page.encode()) <= limit for page in pages)
