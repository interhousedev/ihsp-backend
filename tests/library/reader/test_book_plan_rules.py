"""LIB-11: a textbook plan is a list of sections; the next one follows the last used."""

from app.modules.library.domain.book_plan import (
    MAX_SECTIONS,
    PlanSection,
    find_section,
    next_section,
    validate_sections,
)
from app.modules.library.domain.reader_errors import InvalidBookPlanError

import pytest


def section(n: int, start: int, end: int, title: str = "") -> PlanSection:
    """A section with two hours."""
    return PlanSection(
        n=n, title=title or f"Section {n}", page_from=start, page_to=end, hours=2.0
    )


PLAN = [section(1, 3, 10), section(2, 11, 20), section(3, 21, 30)]


def test_valid_sections_come_back_in_the_given_order() -> None:
    """LIB-11: the plan keeps the order the teacher gave."""
    assert validate_sections(PLAN, page_count=120) == PLAN


@pytest.mark.parametrize(
    "bad",
    [
        PlanSection(n=0, title="x", page_from=1, page_to=2, hours=1),
        PlanSection(n=1, title="  ", page_from=1, page_to=2, hours=1),
        PlanSection(n=1, title="x" * 201, page_from=1, page_to=2, hours=1),
        PlanSection(n=1, title="x", page_from=0, page_to=2, hours=1),
        PlanSection(n=1, title="x", page_from=5, page_to=4, hours=1),
        PlanSection(n=1, title="x", page_from=1, page_to=2, hours=-1),
        PlanSection(n=1, title="x", page_from=1, page_to=2, hours=101),
    ],
)
def test_a_broken_section_is_refused(bad: PlanSection) -> None:
    """LIB-11: titles, numbers, page ranges and hours are checked."""
    with pytest.raises(InvalidBookPlanError):
        validate_sections([bad], page_count=None)


def test_duplicate_section_numbers_are_refused() -> None:
    """LIB-11: `n` identifies a section."""
    with pytest.raises(InvalidBookPlanError):
        validate_sections([section(1, 1, 5), section(1, 6, 9)], page_count=None)


def test_pages_beyond_the_book_are_refused_when_the_length_is_known() -> None:
    """LIB-11: a typo of 540 for 54 is caught."""
    with pytest.raises(InvalidBookPlanError):
        validate_sections([section(1, 1, 121)], page_count=120)

    validate_sections([section(1, 1, 121)], page_count=None)


def test_too_many_sections_are_refused() -> None:
    """LIB-11: a plan is bounded."""
    many = [section(i, 1, 2) for i in range(1, MAX_SECTIONS + 2)]

    with pytest.raises(InvalidBookPlanError):
        validate_sections(many, page_count=None)


def test_find_section_prefers_the_page_range() -> None:
    """LIB-11: a link made from a suggestion matches its section by pages."""
    found = find_section(PLAN, label="whatever", page_from=11, page_to=20)

    assert found == 1


def test_find_section_falls_back_to_the_label() -> None:
    """LIB-11: a hand-typed link matches by title or `n. title`."""
    assert find_section(PLAN, label="Section 3", page_from=None, page_to=None) == 2
    assert find_section(PLAN, label="2. Section 2", page_from=None, page_to=None) == 1
    assert find_section(PLAN, label="nope", page_from=None, page_to=None) is None


def test_next_section_without_a_previous_link_is_the_first() -> None:
    """LIB-11: a fresh class starts at the beginning."""
    assert next_section(PLAN, last=None) == PLAN[0]


def test_next_section_follows_the_last_linked_one() -> None:
    """LIB-11: the suggestion is the section after the last used."""
    last = find_section(PLAN, label="", page_from=11, page_to=20)

    assert next_section(PLAN, last=last) == PLAN[2]


def test_next_section_after_the_last_is_none() -> None:
    """LIB-11: when the book is done there is nothing to suggest."""
    assert next_section(PLAN, last=2) is None


def test_next_section_of_an_empty_plan_is_none() -> None:
    """LIB-11: no sections, no suggestion."""
    assert next_section([], last=None) is None
