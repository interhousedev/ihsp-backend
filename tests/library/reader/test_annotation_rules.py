"""LIB-8: annotations are private notes with a quote, a note and a colour."""

import datetime as dt

from app.modules.library.domain.enums import AnnotationColor, AnnotationKind
from app.modules.library.domain.reader_annotation import (
    MAX_NOTE,
    MAX_QUOTE,
    Annotation,
    build_annotation,
    edit_annotation,
    soft_delete,
)
from app.modules.library.domain.reader_errors import InvalidAnnotationError
from app.shared.ids import new_id

import pytest

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)
LATER = NOW + dt.timedelta(minutes=5)


def make(**fields: object) -> Annotation:
    """A highlight with sensible defaults."""
    values: dict[str, object] = {
        "user_id": new_id(),
        "item_id": new_id(),
        "file_id": new_id(),
        "kind": AnnotationKind.HIGHLIGHT,
        "locator": {"page": 3},
        "quote": "Newton's first law",
        "note": None,
        "color": AnnotationColor.YELLOW,
        "client_id": new_id(),
        "now": NOW,
    }
    values.update(fields)
    return build_annotation(**values)  # type: ignore[arg-type]


def test_new_annotation_gets_an_id_and_timestamps() -> None:
    """LIB-8: a created annotation is alive and stamped."""
    annotation = make()

    assert annotation.created_at == annotation.updated_at == NOW
    assert annotation.deleted_at is None
    assert annotation.id != annotation.client_id


def test_blank_texts_become_none() -> None:
    """LIB-8: an empty note is no note."""
    annotation = make(quote="   ", note="")

    assert annotation.quote is None
    assert annotation.note is None


def test_quote_over_1000_characters_is_refused() -> None:
    """LIB-8: quote is at most 1000 characters."""
    make(quote="q" * MAX_QUOTE)
    with pytest.raises(InvalidAnnotationError) as caught:
        make(quote="q" * (MAX_QUOTE + 1))

    assert caught.value.params["field"] == "quote"


def test_note_over_2000_characters_is_refused() -> None:
    """LIB-8: note is at most 2000 characters."""
    make(note="n" * MAX_NOTE)
    with pytest.raises(InvalidAnnotationError) as caught:
        make(note="n" * (MAX_NOTE + 1))

    assert caught.value.params["field"] == "note"


def test_editing_changes_note_and_colour_and_the_timestamp() -> None:
    """LIB-8: only the note and the colour are editable."""
    annotation = make()

    edited = edit_annotation(
        annotation, note="Remember", color=AnnotationColor.PINK, now=LATER
    )

    assert edited.note == "Remember"
    assert edited.color is AnnotationColor.PINK
    assert edited.quote == annotation.quote
    assert edited.updated_at == LATER


def test_editing_can_clear_the_note() -> None:
    """LIB-8: a note set to null is removed."""
    annotation = make(note="old")

    edited = edit_annotation(annotation, note=None, now=LATER)
    untouched = edit_annotation(annotation, color=AnnotationColor.GREEN, now=LATER)

    assert edited.note is None
    assert untouched.note == "old"


def test_editing_without_changes_keeps_the_timestamp() -> None:
    """LIB-9: a sync that changes nothing does not touch the annotation."""
    annotation = make(note="same", color=AnnotationColor.BLUE)

    edited = edit_annotation(
        annotation, note="same", color=AnnotationColor.BLUE, now=LATER
    )

    assert edited.updated_at == NOW


def test_soft_delete_marks_the_time_once() -> None:
    """LIB-9: deleting is a mark, repeating it keeps the first time."""
    annotation = make()

    gone = soft_delete(annotation, now=LATER)
    again = soft_delete(gone, now=LATER + dt.timedelta(hours=1))

    assert gone.deleted_at == LATER
    assert again.deleted_at == LATER
