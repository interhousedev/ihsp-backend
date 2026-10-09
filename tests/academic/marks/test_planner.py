"""Mark planner: predicted semester mark and what the controls must bring (ACA-15)."""

from collections.abc import Callable
from decimal import Decimal

from app.modules.academic.domain.marks import grading, planner
from app.modules.academic.domain.marks.errors import InvalidWhatIfError
from app.modules.academic.domain.marks.planner import (
    FinalForMidterm,
    HypotheticalMark,
    TargetPlan,
    add_hypothetical,
    assumed_mark,
    grade_of,
    parse_what_if,
    plan,
    threshold,
)

import pytest
from hypothesis import given
from hypothesis import strategies as st

MARKS = st.lists(st.integers(min_value=2, max_value=5), max_size=8)
MIDTERMS = st.lists(st.integers(min_value=2, max_value=5), max_size=3)
FINALS = st.lists(st.integers(min_value=2, max_value=5), max_size=2)


def _target(result: planner.Plan, grade: int) -> TargetPlan:
    return next(t for t in result.targets if t.grade == grade)


@pytest.mark.parametrize(
    ("grade", "expected"), [(5, "4.50"), (4, "3.50"), (3, "2.50"), (2, "1.50")]
)
def test_threshold_is_the_lowest_mark_that_rounds_to_the_grade(
    grade: int, expected: str
) -> None:
    """ACA-15: a mark from 4.50 shows as a 5, from 3.50 as a 4."""
    assert threshold(grade) == Decimal(expected)


@pytest.mark.parametrize(
    ("mark", "grade"),
    [
        ("5.00", 5),
        ("4.50", 5),
        ("4.49", 4),
        ("3.50", 4),
        ("3.49", 3),
        ("2.50", 3),
        ("2.49", 2),
        ("2.00", 2),
    ],
)
def test_grade_rounds_halves_up(mark: str, grade: int) -> None:
    """The whole grade is the semester mark rounded half up."""
    assert grade_of(Decimal(mark)) == grade


@pytest.mark.parametrize(
    ("average", "expected"),
    [
        (None, None),
        ("5.00", 5),
        ("4.50", 5),
        ("4.49", 4),
        ("3.00", 3),
        ("2.49", 2),
        ("2.00", 2),
        ("1.00", 2),
        ("9.00", 5),
    ],
)
def test_pending_control_is_assumed_to_get_the_rounded_lesson_average(
    average: str | None, expected: int | None
) -> None:
    """A control gives a whole mark in 2..5, so the guess is clamped to that range."""
    value = None if average is None else Decimal(average)
    assert assumed_mark(value) == expected


def test_no_marks_at_all_gives_unknown_targets_and_no_prediction() -> None:
    """Without lesson marks there is no base to plan from."""
    result = plan([], [], [])

    assert result.semester_mark is None
    assert result.predicted == planner.Prediction(None, None, None)
    assert [t.status for t in result.targets] == ["unknown"] * 3
    assert result.components == ()
    assert result.missing == ("lesson", "midterm", "final")
    assert result.remaining == planner.Remaining(midterm=2, final=1)
    assert result.pending == ("midterm", "final")
    assert "no_lesson_marks" in result.assumptions
    assert "pending_as_lesson_average" not in result.assumptions


def test_controls_without_lesson_marks_still_make_a_mark_but_no_plan() -> None:
    """ACA-15 averages the types that have marks, so 5 and 5 make a 5.00; but there
    is no lesson average to plan or guess from."""
    result = plan([], [5], [5])

    assert result.semester_mark == Decimal("5.00")
    assert result.components == ("midterm", "final")
    assert result.missing == ("lesson",)
    assert [t.status for t in result.targets] == ["unknown"] * 3
    assert result.predicted.value is None


def test_stats_count_marks_and_round_the_average() -> None:
    """Each type reports how many marks it has and their average."""
    result = plan([5, 4, 4], [3], [])

    assert result.lesson == planner.MarkStat(3, Decimal("4.33"))
    assert result.midterm == planner.MarkStat(1, Decimal("3.00"))
    assert result.final == planner.MarkStat(0, None)


def test_components_and_missing_name_the_types_behind_the_mark() -> None:
    """The page can say "final not yet": missing lists the types without marks."""
    only_lesson = plan([5, 4], [], [])
    assert (only_lesson.components, only_lesson.missing) == (
        ("lesson",),
        ("midterm", "final"),
    )
    midterm = plan([5, 4], [3], [])
    assert (midterm.components, midterm.missing) == (
        ("lesson", "midterm"),
        ("final",),
    )
    everything = plan([5, 4], [3], [5])
    assert (everything.components, everything.missing) == (
        ("lesson", "midterm", "final"),
        (),
    )
    no_midterm = plan([5, 4], [], [5])
    assert no_midterm.missing == ("midterm",)


def test_semester_mark_is_the_aca_15_mark() -> None:
    """The mean of the means of the types that have marks, rounded once."""
    assert plan([5, 4], [], []).semester_mark == Decimal("4.50")
    assert plan([5, 4], [3], []).semester_mark == Decimal("3.75")
    assert plan([5, 4], [], [5]).semester_mark == Decimal("4.75")
    assert plan([5, 4], [3], [5]).semester_mark == Decimal("4.17")


@pytest.mark.parametrize(
    ("midterm", "final", "left_midterm", "left_final", "pending"),
    [
        ([], [], 2, 1, ("midterm", "final")),
        ([4], [], 1, 1, ("midterm", "final")),
        ([4, 4], [], 0, 1, ("final",)),
        ([], [4], 2, 0, ("midterm",)),
        ([4], [4], 1, 0, ("midterm",)),
        ([4, 4], [4], 0, 0, ()),
        ([4, 4, 4], [4, 4], 0, 0, ()),
    ],
)
def test_a_semester_has_two_midterm_controls_and_one_final(
    midterm: list[int],
    final: list[int],
    left_midterm: int,
    left_final: int,
    pending: tuple[str, ...],
) -> None:
    """Remaining controls are what is left of 2 midterms and 1 final."""
    result = plan([5], midterm, final)

    assert result.remaining == planner.Remaining(left_midterm, left_final)
    assert result.pending == pending


def test_prediction_assumes_remaining_controls_equal_the_rounded_lesson_average() -> (
    None
):
    """Lesson average 4.33 -> a 4 on all three controls: (4.33 + 4 + 4) / 3 = 4.11."""
    result = plan([5, 4, 4], [], [])

    assert result.predicted == planner.Prediction(Decimal("4.11"), 4, 4)


def test_prediction_keeps_real_control_marks_and_guesses_the_rest() -> None:
    """Midterm 5 is real, the second midterm and the final are guessed as 4."""
    result = plan([5, 4, 4], [5], [])

    # midterm mean (5 + 4) / 2 = 4.5, final 4: (4.33 + 4.5 + 4) / 3 = 4.28
    assert result.predicted == planner.Prediction(Decimal("4.28"), 4, 4)


def test_prediction_with_both_midterms_done_guesses_only_the_final() -> None:
    """Nothing is guessed for a control that already has its marks."""
    result = plan([5, 4, 4], [5, 4], [])

    assert result.predicted == planner.Prediction(Decimal("4.28"), None, 4)


def test_prediction_of_a_finished_semester_is_the_semester_mark() -> None:
    """Nothing is guessed when every control has its marks."""
    result = plan([5, 4], [3, 4], [5])

    assert result.predicted == planner.Prediction(Decimal("4.33"), None, None)
    assert result.predicted.value == result.semester_mark


def test_prediction_guess_rounds_the_lesson_average_half_up() -> None:
    """Lesson average 4.50 is guessed as a 5: (4.5 + 5 + 5) / 3 = 4.83."""
    result = plan([5, 4], [], [])

    assert result.predicted == planner.Prediction(Decimal("4.83"), 5, 5)


def test_all_controls_remaining_ask_for_a_mark_on_each_kind() -> None:
    """Lesson average 4.50: a 5 needs midterm + final >= 9, a 4 needs >= 6."""
    result = plan([5, 4, 5, 4], [], [])

    five = _target(result, 5)
    assert five.status == "needed"
    assert five.min_both == 5
    assert five.pairs == (
        FinalForMidterm(5, 4),
        FinalForMidterm(4, 5),
        FinalForMidterm(3, None),
        FinalForMidterm(2, None),
    )
    four = _target(result, 4)
    assert four.status == "needed"
    assert four.min_both == 3
    assert four.pairs == (
        FinalForMidterm(5, 2),
        FinalForMidterm(4, 2),
        FinalForMidterm(3, 3),
        FinalForMidterm(2, 4),
    )
    assert _target(result, 3).status == "secured"


def test_midterm_and_final_remaining_can_be_out_of_reach() -> None:
    """Lesson average 2.00: even 5s everywhere give (2 + 5 + 5) / 3 = 4.00."""
    result = plan([2, 2], [], [])

    five = _target(result, 5)
    assert five.status == "not_reachable"
    assert five.min_both is None
    assert five.pairs == ()
    assert _target(result, 4).status == "needed"


def test_a_mark_is_needed_on_the_final_when_the_midterms_are_done() -> None:
    """Lesson 5.00, midterms 4.50: a 5 needs a final of 4, a 4 is already safe."""
    result = plan([5, 5], [5, 4], [])

    five = _target(result, 5)
    assert (five.status, five.control, five.min_value) == ("needed", "final", 4)
    assert _target(result, 4).status == "secured"
    assert _target(result, 3).status == "secured"


def test_a_mark_is_needed_on_the_last_midterm() -> None:
    """Lesson 4, midterm 5 so far, final 5: the second midterm must be a 4 for a 5."""
    result = plan([4, 4], [5], [5])

    five = _target(result, 5)
    assert (five.status, five.control, five.min_value) == ("needed", "midterm", 4)


def test_two_remaining_midterms_need_the_same_mark_each() -> None:
    """Lesson 4, final 5: a 5 needs a 5 on each of the two midterms."""
    result = plan([4, 4], [], [5])

    five = _target(result, 5)
    assert result.remaining == planner.Remaining(midterm=2, final=0)
    assert (five.status, five.control, five.min_value) == ("needed", "midterm", 5)
    assert "same_mark_on_remaining" in result.assumptions


def test_one_remaining_control_can_be_out_of_reach() -> None:
    """Lesson 3, midterms 3: a final of 5 gives 3.67, so a 5 is out of reach."""
    result = plan([3, 3], [3, 3], [])

    assert _target(result, 5).status == "not_reachable"
    four = _target(result, 4)
    assert (four.status, four.control, four.min_value) == ("needed", "final", 5)
    assert _target(result, 3).status == "secured"


def test_finished_semester_is_secured_or_not_reachable() -> None:
    """With no control left the grade is decided: 4.11 is a 4."""
    result = plan([5, 4, 4], [4, 4], [4])

    assert result.pending == ()
    assert [t.status for t in result.targets] == ["not_reachable", "secured", "secured"]
    assert all(t.min_value is None and t.pairs == () for t in result.targets)


def test_targets_are_listed_from_five_to_three() -> None:
    """The UI shows 5, 4, 3 in that order with their thresholds."""
    result = plan([4], [], [])

    assert [t.grade for t in result.targets] == [5, 4, 3]
    assert [t.threshold for t in result.targets] == [
        Decimal("4.50"),
        Decimal("3.50"),
        Decimal("2.50"),
    ]


def test_assumptions_name_what_the_numbers_rest_on() -> None:
    """Rounding always; the control count and the guess while a control is open."""
    assert plan([4], [], []).assumptions == (
        "rounding",
        "controls_per_semester",
        "same_mark_on_remaining",
        "pending_as_lesson_average",
    )
    assert plan([4], [4], [4]).assumptions == (
        "rounding",
        "controls_per_semester",
        "pending_as_lesson_average",
    )
    assert plan([4], [4, 4], [4]).assumptions == ("rounding",)


def test_what_if_is_named_in_the_assumptions() -> None:
    """Hypothetical marks are flagged so the page can say so."""
    assert "what_if" in plan([4, 5], [], [], what_if_count=1).assumptions
    assert "what_if" not in plan([4, 5], [], []).assumptions


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("lesson:5", HypotheticalMark("lesson", 5)),
        ("midterm:2", HypotheticalMark("midterm", 2)),
        ("final:4", HypotheticalMark("final", 4)),
    ],
)
def test_what_if_marks_are_parsed(raw: str, expected: HypotheticalMark) -> None:
    """A hypothetical mark is written ``<type>:<value>``."""
    assert parse_what_if(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "lesson", "lesson:", "lesson:1", "lesson:6", "lesson:-3", "exam:4"]
    + ["lesson:4.5", "Lesson:4", "lesson:\u00b2", ":4", "lesson:4:4", "lesson: 4"],
)
def test_bad_what_if_marks_are_refused(raw: str) -> None:
    """Unknown types and marks outside 2..5 are a validation error."""
    with pytest.raises(InvalidWhatIfError):
        parse_what_if(raw)


def test_hypothetical_marks_are_added_to_their_type() -> None:
    """The real lists are not touched; the answer has the extra marks appended."""
    lesson: list[int] = [5]
    midterm: list[int] = []
    final: list[int] = [3]

    got = add_hypothetical(
        lesson,
        midterm,
        final,
        [
            HypotheticalMark("lesson", 4),
            HypotheticalMark("midterm", 5),
            HypotheticalMark("lesson", 3),
        ],
    )

    assert got == ([5, 4, 3], [5], [3])
    assert (lesson, midterm, final) == ([5], [], [3])


def test_too_many_hypothetical_marks_are_refused() -> None:
    """A what-if is a small experiment, not a data upload."""
    many = [HypotheticalMark("lesson", 5)] * (planner.MAX_WHAT_IF + 1)

    with pytest.raises(InvalidWhatIfError):
        add_hypothetical([], [], [], many)
    assert len(add_hypothetical([], [], [], many[:-1])[0]) == planner.MAX_WHAT_IF


LESSON_SETS = [[], [2], [3], [4], [5], [5, 4], [4, 4, 5], [2, 3], [3, 3, 4, 4], [5] * 6]
MIDTERM_SETS = [[], [2], [3], [4], [5], [5, 4], [2, 3], [4, 4], [3, 5]]
FINAL_SETS = [[], [2], [3], [4], [5]]
_RANK = {"secured": 0, "needed": 1, "not_reachable": 2}


def _reaches(value: Decimal | None, limit: Decimal) -> bool:
    return value is not None and value >= limit


def _outcome(
    lesson: list[int], midterm: list[int], final: list[int], m: int, f: int
) -> Decimal | None:
    """Semester mark if every remaining midterm gets ``m`` and the final ``f``.

    The reference uses its own count of what is left of 2 midterms and 1 final.
    """
    left_midterm = max(0, 2 - len(midterm))
    left_final = max(0, 1 - len(final))
    return grading.semester_mark(
        lesson, [*midterm, *[m] * left_midterm], [*final, *[f] * left_final]
    )


@pytest.mark.parametrize("lesson", LESSON_SETS)
@pytest.mark.parametrize("midterm", MIDTERM_SETS)
@pytest.mark.parametrize("final", FINAL_SETS)
def test_every_target_agrees_with_trying_every_mark(
    lesson: list[int], midterm: list[int], final: list[int]
) -> None:
    """Exhaustive: each statement is checked against `grading.semester_mark`."""
    result = plan(lesson, midterm, final)
    pending = tuple(
        control
        for control, left in (("midterm", 2 - len(midterm)), ("final", 1 - len(final)))
        if left > 0
    )

    assert result.pending == pending
    for target in result.targets:
        _check_target(target, pending, lesson, midterm, final)


def _check_target(
    target: TargetPlan,
    pending: tuple[str, ...],
    lesson: list[int],
    midterm: list[int],
    final: list[int],
) -> None:
    limit = threshold(target.grade)

    def reaches(m: int, f: int) -> bool:
        return _reaches(_outcome(lesson, midterm, final, m, f), limit)

    if not lesson:
        assert target.status == "unknown"
    elif pending == ():
        assert (target.status == "secured") == reaches(2, 2)
        assert target.status in ("secured", "not_reachable")
    elif pending == ("final",):
        _check_single(target, [reaches(2, v) for v in range(2, 6)], "final")
    elif pending == ("midterm",):
        _check_single(target, [reaches(v, 2) for v in range(2, 6)], "midterm")
    else:
        _check_both(target, reaches)


def _check_single(target: TargetPlan, reach: list[bool], control: str) -> None:
    """``reach[i]`` tells whether a control mark of ``i + 2`` gets the grade."""
    if target.status == "secured":
        assert all(reach)
    elif target.status == "not_reachable":
        assert not any(reach)
    else:
        assert target.status == "needed"
        assert target.control == control
        assert target.min_value is not None
        assert target.min_value > 2
        assert reach[target.min_value - 2]
        assert not reach[target.min_value - 3]  # one mark lower falls short


def _check_both(target: TargetPlan, reaches: Callable[[int, int], bool]) -> None:
    if target.status == "secured":
        assert reaches(2, 2)
    elif target.status == "not_reachable":
        assert not reaches(5, 5)
        assert target.pairs == ()
    else:
        assert target.status == "needed"
        assert target.min_both is not None
        assert reaches(target.min_both, target.min_both)
        assert target.min_both == 2 or not reaches(
            target.min_both - 1, target.min_both - 1
        )
        assert [p.midterm for p in target.pairs] == [5, 4, 3, 2]
        for pair in target.pairs:
            if pair.min_final is None:
                assert not reaches(pair.midterm, 5)
            else:
                assert reaches(pair.midterm, pair.min_final)
                assert pair.min_final == 2 or not reaches(
                    pair.midterm, pair.min_final - 1
                )


@given(lesson=MARKS, midterm=MIDTERMS, final=FINALS)
def test_a_higher_grade_is_never_easier(
    lesson: list[int], midterm: list[int], final: list[int]
) -> None:
    """Property: if a 4 is not secured, a 5 is not secured either."""
    result = plan(lesson, midterm, final)

    if lesson:
        ranks = [_RANK[t.status] for t in result.targets]  # grades 5, 4, 3
        assert ranks == sorted(ranks, reverse=True)


@given(lesson=MARKS, midterm=MIDTERMS, final=FINALS)
def test_planner_mark_always_equals_the_formula(
    lesson: list[int], midterm: list[int], final: list[int]
) -> None:
    """Property: the planner never re-implements ACA-15, it reports it."""
    result = plan(lesson, midterm, final)

    assert result.semester_mark == grading.semester_mark(lesson, midterm, final)
    assert result.lesson.average == grading.average(lesson)
    assert set(result.components) | set(result.missing) == {
        "lesson",
        "midterm",
        "final",
    }
    assert not set(result.components) & set(result.missing)
    if not result.pending and lesson:
        mark = result.semester_mark
        assert mark is not None
        for target in result.targets:
            assert (target.status == "secured") == (mark >= threshold(target.grade))
