"""LIB-10, NB-2: titles, keys and the text of library sources (pure rules)."""

import datetime as dt
from typing import Literal

from app.modules.notebooks.domain.library_sources import (
    library_key,
    library_title,
    notes_key,
    notes_version,
    pages_label,
    render_notes,
)
from app.shared.contracts.library import LibraryAnnotationRef
from app.shared.ids import new_id

import pytest

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def annotation(
    *,
    kind: Literal["highlight", "note", "bookmark"] = "highlight",
    quote: str | None = "Newton's first law",
    note: str | None = None,
    page: int | None = 54,
    minutes: int = 0,
) -> LibraryAnnotationRef:
    """One annotation of the student."""
    return LibraryAnnotationRef(
        kind=kind,
        quote=quote,
        note=note,
        page=page,
        color="yellow",
        updated_at=NOW + dt.timedelta(minutes=minutes),
    )


# - - - titles - - -


@pytest.mark.parametrize(
    ("page_from", "page_to", "label"),
    [
        (54, 61, "pp. 54-61"),
        (54, 54, "p. 54"),
        (54, None, "from p. 54"),
        (None, 12, "pp. 1-12"),
        (None, None, ""),
    ],
)
def test_the_pages_of_a_source_are_labelled_like_a_citation(
    page_from: int | None, page_to: int | None, label: str
) -> None:
    """LIB-10: "Physics 10, pp. 54-61" is how the source reads in the list."""
    assert pages_label(page_from, page_to) == label


def test_the_title_of_a_chapter_source_ends_with_its_pages() -> None:
    """LIB-10: the title and the pages are both visible."""
    assert library_title("Physics 10", 54, 61) == "Physics 10, pp. 54-61"


def test_the_title_of_a_whole_book_has_no_pages() -> None:
    """LIB-10: no range, no suffix."""
    assert library_title("Physics 10", None, None) == "Physics 10"


def test_a_very_long_title_is_cut_before_the_pages_not_after_them() -> None:
    """LIB-10: the source title column holds 255 characters; pages must survive."""
    title = library_title("A" * 400, 54, 61)

    assert len(title) == 255
    assert title.endswith(", pp. 54-61")


# - - - keys - - -


def test_a_chapter_is_identified_by_file_and_pages() -> None:
    """LIB-10: the shared document of a chapter is keyed by (file, from, to)."""
    file_id = new_id()

    assert library_key(file_id, 54, 61) == f"library:{file_id}:54:61"


def test_an_open_range_has_its_own_key() -> None:
    """LIB-10: the whole file and a chapter of it are different documents."""
    file_id = new_id()

    assert library_key(file_id, None, None) == f"library:{file_id}:1:0"
    assert library_key(file_id, None, None) != library_key(file_id, 1, 10)


def test_the_notes_of_a_book_are_keyed_by_the_book() -> None:
    """LIB-10: one notes source per book in a notebook."""
    item_id = new_id()

    assert notes_key(item_id) == f"library-notes:{item_id}"


# - - - notes as Markdown - - -


def test_a_highlight_reads_as_a_quote_with_its_page() -> None:
    """LIB-10: "quote (p. N)" under a heading with the book."""
    text = render_notes("Physics 10", [annotation()])

    assert text == (
        "# Highlights and notes: Physics 10\n\n> Newton's first law (p. 54)\n"
    )


def test_a_note_follows_its_quote_in_the_same_block() -> None:
    """LIB-10: quote, page and the student's note stay together."""
    text = render_notes(
        "Physics 10", [annotation(kind="note", note="Key idea for the exam")]
    )

    assert "> Newton's first law (p. 54)\nKey idea for the exam\n" in text


def test_a_note_without_a_quote_carries_the_page() -> None:
    """LIB-10: free notes are kept."""
    text = render_notes(
        "Physics 10", [annotation(kind="note", quote=None, note="Ask the teacher")]
    )

    assert "Ask the teacher (p. 54)\n" in text


def test_text_is_flattened_so_that_blocks_are_not_split() -> None:
    """LIB-10: a blank line inside a quote would cut it into two passages."""
    text = render_notes(
        "Physics 10",
        [annotation(quote="first line\n\nsecond   line", note="a\n\nb")],
    )

    assert "> first line second line (p. 54)\na b\n" in text


def test_bookmarks_and_empty_annotations_add_nothing() -> None:
    """LIB-10: they have no words to learn from."""
    text = render_notes(
        "Physics 10",
        [
            annotation(kind="bookmark", quote=None, note=None),
            annotation(quote="  ", note=None),
        ],
    )

    assert text == ""


def test_annotations_are_listed_in_reading_order() -> None:
    """LIB-10: by page, then by time; those without a page come last."""
    text = render_notes(
        "Physics 10",
        [
            annotation(quote="no page", page=None, minutes=1),
            annotation(quote="late on p. 9", page=9, minutes=2),
            annotation(quote="early on p. 3", page=3, minutes=3),
            annotation(quote="also p. 9", page=9, minutes=4),
        ],
    )

    order = [line for line in text.splitlines() if line.startswith(">")]
    assert order == [
        "> early on p. 3 (p. 3)",
        "> late on p. 9 (p. 9)",
        "> also p. 9 (p. 9)",
        "> no page",
    ]


# - - - the version of the notes - - -


def test_the_version_is_stable_for_the_same_annotations() -> None:
    """LIB-10: nothing changed, nothing to sync."""
    assert notes_version([annotation()]) == notes_version([annotation()])


def test_the_version_is_short_enough_for_the_column() -> None:
    """LIB-10: `upstream_version` holds 64 characters."""
    assert len(notes_version([annotation()])) <= 64


@pytest.mark.parametrize(
    "changed",
    [
        [annotation(note="now with a note")],
        [annotation(minutes=5)],
        [annotation(), annotation(quote="second")],
        [],
    ],
)
def test_the_version_changes_with_the_annotations(
    changed: list[LibraryAnnotationRef],
) -> None:
    """LIB-10: an edit, an addition or a deletion makes the source outdated."""
    assert notes_version(changed) != notes_version([annotation()])


def test_the_version_ignores_the_order_the_annotations_arrive_in() -> None:
    """LIB-10: only the content counts."""
    first, second = annotation(quote="one"), annotation(quote="two", page=3)

    assert notes_version([first, second]) == notes_version([second, first])
