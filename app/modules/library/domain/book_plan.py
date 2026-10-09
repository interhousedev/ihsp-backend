"""Textbook plans: the sections of a book planned for a subject and year (LIB-11)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from app.modules.library.domain.reader_errors import InvalidBookPlanError

MAX_SECTIONS = 300
MAX_TITLE = 200
MAX_HOURS = 100


@dataclass(frozen=True, slots=True)
class PlanSection:
    """A chapter of the book with its pages and the hours planned for it."""

    n: int
    title: str
    page_from: int
    page_to: int
    hours: float


@dataclass(frozen=True, slots=True)
class BookPlan:
    """The sections of one book for a subject and a year of study."""

    id: UUID
    subject_id: UUID
    year_of_study: int
    item_id: UUID
    sections: tuple[PlanSection, ...]
    updated_at: datetime


def _invalid(field: str, section: PlanSection | None = None) -> InvalidBookPlanError:
    params: dict[str, object] = {"field": field}
    if section is not None:
        params["n"] = section.n
    return InvalidBookPlanError(params=params)


def _check_section(section: PlanSection, page_count: int | None) -> None:
    if section.n < 1:
        raise _invalid("n", section)
    if not 0 < len(section.title.strip()) <= MAX_TITLE:
        raise _invalid("title", section)
    if section.page_from < 1 or section.page_to < section.page_from:
        raise _invalid("pages", section)
    if page_count is not None and section.page_to > page_count:
        raise _invalid("pages", section)
    if not 0 <= section.hours <= MAX_HOURS:
        raise _invalid("hours", section)


def validate_sections(
    sections: Sequence[PlanSection], *, page_count: int | None
) -> list[PlanSection]:
    """The sections in the given order, or `InvalidBookPlanError`.

    Page numbers are compared with `page_count` only when the book's length is known.
    """
    if len(sections) > MAX_SECTIONS:
        raise _invalid("sections")
    seen: set[int] = set()
    for section in sections:
        _check_section(section, page_count)
        if section.n in seen:
            raise _invalid("n", section)
        seen.add(section.n)
    return list(sections)


def find_section(
    sections: Sequence[PlanSection],
    *,
    label: str,
    page_from: int | None,
    page_to: int | None,
) -> int | None:
    """Index of the section a lesson link points at, or None.

    The page range is the reliable key (a link made from a suggestion has the same
    range); a hand-typed link is matched by the title or by `n. title`.
    """
    if page_from is not None and page_to is not None:
        for index, section in enumerate(sections):
            if (section.page_from, section.page_to) == (page_from, page_to):
                return index
    wanted = label.strip().casefold()
    for index, section in enumerate(sections):
        title = section.title.strip().casefold()
        if wanted in (title, f"{section.n}. {title}"):
            return index
    return None


def next_section(
    sections: Sequence[PlanSection], *, last: int | None
) -> PlanSection | None:
    """The section after index `last` (the first when `last` is None), or None."""
    following = 0 if last is None else last + 1
    return sections[following] if following < len(sections) else None
