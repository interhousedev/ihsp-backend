"""ACA-2, ACA-6, STF-8: who is expected at a lesson."""

from uuid import UUID

from app.modules.academic.domain import audience
from app.modules.academic.domain.classwork.roster import RosterStudent, build_roster
from app.shared.ids import new_id

G1, G2 = new_id(), new_id()


def make_student(
    last: str, first: str, group: UUID = G1, subgroup: int | None = None
) -> RosterStudent:
    """Build a roster student of a group."""
    return RosterStudent(
        user_id=new_id(),
        first_name=first,
        last_name=last,
        group_id=group,
        group_name="2TN2" if group == G1 else "2TN1",
        subgroup=subgroup,
    )


def names(students: tuple[RosterStudent, ...]) -> list[str]:
    """Last names, for readable assertions."""
    return [s.last_name for s in students]


def test_whole_group_lesson_expects_every_student_even_without_subgroup() -> None:
    """ACA-2: a whole-group lesson counts students whatever their subgroup."""
    students = [
        make_student("Abdullaev", "Aziz", subgroup=1),
        make_student("Karimov", "Bobur", subgroup=2),
        make_student("Rakhimova", "Camila"),
    ]

    roster = build_roster([audience.key(G1, None)], students)

    assert names(roster.expected) == ["Abdullaev", "Karimov", "Rakhimova"]
    assert roster.unassigned == ()


def test_subgroup_lesson_lists_students_without_subgroup_apart() -> None:
    """ACA-2: unassigned students are separate and counted only if marked."""
    students = [
        make_student("Abdullaev", "Aziz", subgroup=1),
        make_student("Karimov", "Bobur", subgroup=2),
        make_student("Rakhimova", "Camila"),
    ]

    roster = build_roster([audience.key(G1, 1)], students)

    assert names(roster.expected) == ["Abdullaev"]
    assert names(roster.unassigned) == ["Rakhimova"]


def test_merged_lesson_collects_students_of_both_groups() -> None:
    """ACA-6: 2TN1/2 + 2TN2/2 is one audience."""
    students = [
        make_student("Karimov", "Bobur", G1, 2),
        make_student("Abdullaev", "Aziz", G1, 1),
        make_student("Saidova", "Dilnoza", G2, 2),
        make_student("Umarov", "Eldor", G2, 1),
    ]

    roster = build_roster([audience.key(G1, 2), audience.key(G2, 2)], students)

    assert names(roster.expected) == ["Karimov", "Saidova"]


def test_students_are_sorted_by_last_name_first_name_and_group() -> None:
    """STF-8: a stable order for positions."""
    students = [
        make_student("Karimov", "Zafar"),
        make_student("karimov", "Anvar"),
        make_student("Abdullaev", "Aziz"),
    ]

    roster = build_roster([audience.key(G1, None)], students)

    assert [(s.last_name, s.first_name) for s in roster.expected] == [
        ("Abdullaev", "Aziz"),
        ("karimov", "Anvar"),
        ("Karimov", "Zafar"),
    ]


def test_positions_run_over_expected_then_unassigned() -> None:
    """BOT-16: a button carries the position in expected + unassigned."""
    students = [
        make_student("Abdullaev", "Aziz", subgroup=1),
        make_student("Rakhimova", "Camila"),
    ]

    roster = build_roster([audience.key(G1, 1)], students)

    assert roster.student_at(0) is roster.expected[0]
    assert roster.student_at(1) is roster.unassigned[0]
    assert roster.student_at(2) is None
    assert roster.student_at(-1) is None


def test_students_saved_in_a_snapshot_stay_expected_after_they_left() -> None:
    """ACA-11: statistics stay correct when groups change later."""
    stayed = make_student("Abdullaev", "Aziz")
    moved = make_student("Saidova", "Dilnoza", G2)

    roster = build_roster([audience.key(G1, None)], [stayed], extra=[moved])

    assert names(roster.expected) == ["Abdullaev", "Saidova"]
