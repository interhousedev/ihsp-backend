"""A lesson follows a section of a book; never touches `Lesson.topic` (LIB-11)."""

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.modules.library.domain.reader_errors import InvalidLessonRefError

MAX_REFS_PER_LESSON = 20
MAX_LABEL = 200


@dataclass(frozen=True, slots=True)
class LessonRefInput:
    """One link a teacher sets on a lesson."""

    item_id: UUID
    section_label: str
    page_from: int | None
    page_to: int | None


def _check_ref(ref: LessonRefInput) -> None:
    if not 0 < len(ref.section_label.strip()) <= MAX_LABEL:
        raise InvalidLessonRefError(params={"field": "section_label"})
    if (ref.page_from is None) != (ref.page_to is None):
        raise InvalidLessonRefError(params={"field": "pages"})
    if ref.page_from is not None and ref.page_to is not None:
        if ref.page_from < 1 or ref.page_to < ref.page_from:
            raise InvalidLessonRefError(params={"field": "pages"})


def validate_refs(refs: Sequence[LessonRefInput]) -> list[LessonRefInput]:
    """The links in the given order, or `InvalidLessonRefError`."""
    if len(refs) > MAX_REFS_PER_LESSON:
        raise InvalidLessonRefError(
            params={"field": "refs", "max": MAX_REFS_PER_LESSON}
        )
    seen: set[tuple[UUID, int | None, int | None, str]] = set()
    for ref in refs:
        _check_ref(ref)
        key = (ref.item_id, ref.page_from, ref.page_to, ref.section_label.strip())
        if key in seen:
            raise InvalidLessonRefError(params={"field": "refs"})
        seen.add(key)
    return list(refs)
