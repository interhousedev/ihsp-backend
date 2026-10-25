"""LIB-10: a page range of a file's text, cut by the page offsets."""

from app.modules.library.domain.bridge_rules import slice_pages

from hypothesis import given
from hypothesis import strategies as st

PAGES = ["First page.\n", "Second page.\n", "Third page.\n", "Fourth page.\n"]
TEXT = "".join(PAGES)
STARTS = (0, 12, 25, 37)


def test_the_whole_text_is_one_range_from_the_first_to_the_last_page() -> None:
    """LIB-10: no range means every page."""
    result = slice_pages(TEXT, STARTS, None, None)

    assert result is not None
    assert (result.text, result.page_starts) == (TEXT, STARTS)
    assert (result.page_from, result.page_to) == (1, 4)


def test_a_range_keeps_the_joined_pages_and_restarts_the_offsets() -> None:
    """LIB-10: pages 2 to 3 start at offset 0 of the slice."""
    result = slice_pages(TEXT, STARTS, 2, 3)

    assert result is not None
    assert result.text == PAGES[1] + PAGES[2]
    assert result.page_starts == (0, len(PAGES[1]))
    assert (result.page_from, result.page_to) == (2, 3)


def test_the_last_page_runs_to_the_end_of_the_text() -> None:
    """LIB-10: the final page has no next start."""
    result = slice_pages(TEXT, STARTS, 4, None)

    assert result is not None
    assert (result.text, result.page_starts) == (PAGES[3], (0,))


def test_a_range_past_the_end_is_cut_to_the_last_page() -> None:
    """LIB-10: the reader clamps what the student asked for."""
    result = slice_pages(TEXT, STARTS, 3, 99)

    assert result is not None
    assert (result.page_from, result.page_to) == (3, 4)
    assert result.text == PAGES[2] + PAGES[3]


def test_a_range_that_starts_past_the_end_is_empty() -> None:
    """LIB-10: nothing to read there."""
    assert slice_pages(TEXT, STARTS, 5, 9) is None


def test_a_reversed_range_is_empty() -> None:
    """LIB-10: from after to selects nothing."""
    assert slice_pages(TEXT, STARTS, 3, 2) is None


def test_a_file_without_page_marks_counts_as_one_page() -> None:
    """LIB-10: markdown and text files have no pages."""
    result = slice_pages("Just text.", (), None, None)

    assert result is not None
    assert (result.text, result.page_starts) == ("Just text.", (0,))
    assert (result.page_from, result.page_to) == (1, 1)


def test_a_range_on_a_file_without_page_marks_is_empty_beyond_page_one() -> None:
    """LIB-10: there is no page 2 in a plain text file."""
    assert slice_pages("Just text.", (), 2, 3) is None


@given(
    pages=st.lists(st.text(min_size=0, max_size=30), min_size=1, max_size=12),
    data=st.data(),
)
def test_any_range_equals_the_joined_pages(
    pages: list[str], data: st.DataObject
) -> None:
    """LIB-10: the slice is exactly the pages of the range, offsets included."""
    starts: list[int] = []
    text = ""
    for page in pages:
        starts.append(len(text))
        text += page
    first = data.draw(st.integers(min_value=1, max_value=len(pages)))
    last = data.draw(st.integers(min_value=first, max_value=len(pages)))

    result = slice_pages(text, tuple(starts), first, last)

    assert result is not None
    assert result.text == "".join(pages[first - 1 : last])
    assert len(result.page_starts) == last - first + 1
    for offset, page in zip(result.page_starts, pages[first - 1 : last], strict=True):
        assert result.text[offset : offset + len(page)] == page
