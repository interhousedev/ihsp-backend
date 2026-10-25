"""LIB-11: a lesson links to sections of books; the links are checked before saving."""

from app.modules.library.domain.reader_errors import InvalidLessonRefError
from app.modules.library.domain.reader_lesson_ref import (
    MAX_REFS_PER_LESSON,
    LessonRefInput,
    validate_refs,
)
from app.shared.ids import new_id

import pytest

ITEM = new_id()


def ref(**fields: object) -> LessonRefInput:
    """A link to pages 54 to 61."""
    values: dict[str, object] = {
        "item_id": ITEM,
        "section_label": "Section 12",
        "page_from": 54,
        "page_to": 61,
    }
    values.update(fields)
    return LessonRefInput(**values)  # type: ignore[arg-type]


def test_valid_refs_are_kept_in_order() -> None:
    """LIB-11: the teacher's order is the display order."""
    refs = [
        ref(section_label="A"),
        ref(section_label="B", page_from=None, page_to=None),
    ]

    assert validate_refs(refs) == refs


@pytest.mark.parametrize(
    "bad",
    [
        ref(section_label="   "),
        ref(section_label="x" * 201),
        ref(page_from=0),
        ref(page_from=9, page_to=3),
        ref(page_from=None, page_to=7),
    ],
)
def test_a_broken_ref_is_refused(bad: LessonRefInput) -> None:
    """LIB-11: label length and the page range are checked."""
    with pytest.raises(InvalidLessonRefError):
        validate_refs([bad])


def test_too_many_refs_are_refused() -> None:
    """LIB-11: a lesson links to a handful of sections."""
    refs = [ref(section_label=f"S{i}") for i in range(MAX_REFS_PER_LESSON + 1)]

    with pytest.raises(InvalidLessonRefError):
        validate_refs(refs)


def test_the_same_section_twice_is_refused() -> None:
    """LIB-11: no duplicates of an item and pages."""
    with pytest.raises(InvalidLessonRefError):
        validate_refs([ref(), ref()])
