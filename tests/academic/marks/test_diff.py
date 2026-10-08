"""Mark identity: ordinals, diff, restore (SYNC-5)."""

import datetime as dt

from app.modules.academic.domain.marks.diff import (
    MarkKey,
    diff,
    split_restored,
    with_ordinals,
)
from app.shared.contracts.emis import EmisMark, EmisMarkType

DAY = dt.date(2026, 10, 6)


def _mark(
    value: int, day: dt.date = DAY, kind: EmisMarkType = EmisMarkType.LESSON
) -> EmisMark:
    return EmisMark(kind, day, value)


def test_identical_marks_of_a_day_get_ordinals_in_input_order() -> None:
    """Two fives on one day are #1 and #2; a four is its own #1."""
    keys = with_ordinals([_mark(5), _mark(4), _mark(5)])
    assert [(k.value, k.ordinal) for k in keys] == [(5, 1), (4, 1), (5, 2)]


def test_ordinals_restart_for_another_day_or_type() -> None:
    """Ordinals count within (type, date, value)."""
    keys = with_ordinals(
        [_mark(5), _mark(5, dt.date(2026, 10, 7)), _mark(5, kind=EmisMarkType.FINAL)]
    )
    assert {k.ordinal for k in keys} == {1}


def test_losing_one_of_two_identical_marks_removes_the_second() -> None:
    """EMIS going from [5, 5] to [5] removes the mark with ordinal 2."""
    stored = with_ordinals([_mark(5), _mark(5)])
    added, removed = diff(stored, with_ordinals([_mark(5)]))
    assert added == []
    assert removed == [MarkKey(EmisMarkType.LESSON, DAY, 5, 2)]


def test_new_mark_is_added() -> None:
    """A mark absent from the stored set is added."""
    stored = with_ordinals([_mark(5)])
    added, removed = diff(stored, with_ordinals([_mark(5), _mark(3)]))
    assert [k.value for k in added] == [3]
    assert removed == []


def test_a_removed_mark_that_returns_is_restored_not_new() -> None:
    """split_restored keeps a returning mark out of the new list."""
    gone = [MarkKey(EmisMarkType.LESSON, DAY, 5, 2)]
    added = [
        MarkKey(EmisMarkType.LESSON, DAY, 5, 2),
        MarkKey(EmisMarkType.LESSON, DAY, 3, 1),
    ]
    new, restored = split_restored(added, gone)
    assert [k.value for k in new] == [3]
    assert restored == gone
