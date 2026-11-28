"""Pure ranking rules of the "My group" standings."""

import datetime as dt
from uuid import UUID

from app.modules.academic.domain.marks.group_standing import (
    StudentStanding,
    current_term,
    group_rankings,
    group_standings,
    in_scope,
    places,
)

G1, G2, G3 = UUID(int=1), UUID(int=2), UUID(int=3)


def _s(
    uid: int, group: UUID, course: int, marks: tuple[int, int], att: tuple[int, int]
) -> StudentStanding:
    return StudentStanding(
        student_id=UUID(int=100 + uid),
        group_id=group,
        group_name=f"G{group.int}",
        course=course,
        grade_sum=marks[0],
        grade_count=marks[1],
        present=att[0],
        absent=att[1],
    )


def test_ties_share_a_place_and_missing_values_are_unranked() -> None:
    assert places([("a", 5.0), ("b", 4.0), ("c", 5.0), ("d", None)]) == {
        "a": 1,
        "c": 1,
        "b": 3,
    }


def test_student_values() -> None:
    s = _s(1, G1, 1, (9, 2), (3, 1))
    assert s.gpa == 4.5
    assert s.attendance == 75.0
    assert _s(2, G1, 1, (0, 0), (0, 0)).gpa is None


def test_group_aggregates_and_scopes() -> None:
    groups = group_standings(
        [
            _s(1, G1, 1, (10, 2), (9, 1)),
            _s(2, G1, 1, (8, 2), (10, 0)),
            _s(3, G2, 1, (10, 2), (5, 5)),
            _s(4, G3, 2, (0, 0), (0, 0)),
        ]
    )
    by_id = {g.group_id: g for g in groups}
    assert by_id[G1].gpa == 4.5 and by_id[G1].attendance == 95.0
    assert by_id[G1].members_count == 2
    course1 = in_scope(groups, "course", 1)
    assert {g.group_id for g in course1} == {G1, G2}
    ranked = group_rankings(in_scope(groups, "lyceum", 1), "gpa")
    assert [(p, g.group_id) for p, g in ranked] == [(1, G2), (2, G1), (None, G3)]


def test_current_term_prefers_containing_then_latest_started() -> None:
    a = (dt.date(2026, 9, 1), dt.date(2026, 12, 31))
    b = (dt.date(2027, 1, 10), dt.date(2027, 5, 31))
    assert current_term([a, b], dt.date(2026, 10, 1)) == a
    assert current_term([a, b], dt.date(2027, 1, 5)) == a
    assert current_term([a, b], dt.date(2026, 8, 1)) == a
    assert current_term([], dt.date(2026, 8, 1)) is None
