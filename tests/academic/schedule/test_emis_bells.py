"""ACA-4: EMIS class hours become the bells of the term (pair 0 is period 1)."""

import datetime as dt

from app.modules.academic.domain.schedule.emis_bells import (
    bells_from_class_hours,
    merge_emis_bells,
)
from app.modules.academic.domain.schedule.term import Bell
from app.modules.identity.infrastructure.emis.fake import FAKE_CLASS_HOURS
from app.shared.contracts.emis import EmisClassHour


def manual(period: int, start: dt.time, end: dt.time, weekdays: list[int]) -> Bell:
    return Bell(period=period, start=start, end=end, weekdays=weekdays)


def test_pair_zero_is_period_one_on_every_study_weekday() -> None:
    """ACA-4: the five EMIS pairs become periods 1-5, Monday to Saturday."""
    bells = bells_from_class_hours(FAKE_CLASS_HOURS)

    assert [(b.period, b.start, b.end) for b in bells] == [
        (1, dt.time(8, 30), dt.time(9, 50)),
        (2, dt.time(10, 10), dt.time(11, 30)),
        (3, dt.time(12, 10), dt.time(13, 30)),
        (4, dt.time(13, 40), dt.time(15, 0)),
        (5, dt.time(15, 10), dt.time(16, 30)),
    ]
    assert all(b.weekdays == [1, 2, 3, 4, 5, 6] for b in bells)
    assert {b.source for b in bells} == {"emis"}


def test_bells_are_ordered_by_pair_even_if_emis_is_not() -> None:
    """ACA-4: the order of the EMIS answer does not matter."""
    shuffled = [FAKE_CLASS_HOURS[3], FAKE_CLASS_HOURS[0], FAKE_CLASS_HOURS[1]]

    assert [b.period for b in bells_from_class_hours(shuffled)] == [1, 2, 4]


def test_the_same_bells_change_nothing() -> None:
    """ACA-4: written only when they differ."""
    from_emis = bells_from_class_hours(FAKE_CLASS_HOURS)

    assert merge_emis_bells(list(from_emis), from_emis) is None
    assert merge_emis_bells(list(reversed(from_emis)), from_emis) is None


def test_emis_replaces_manual_bells_of_the_periods_it_lists() -> None:
    """ACA-4: EMIS wins for periods 1-5, including Saturday's own times."""
    current = [
        manual(1, dt.time(8, 30), dt.time(9, 15), [1, 2, 3, 4, 5]),
        manual(1, dt.time(8, 30), dt.time(9, 5), [6]),
    ]

    merged = merge_emis_bells(current, bells_from_class_hours(FAKE_CLASS_HOURS))

    assert merged is not None
    assert [(b.period, b.source) for b in merged] == [(p, "emis") for p in range(1, 6)]


def test_manual_bells_of_other_periods_stay() -> None:
    """ACA-4: a sixth period set by Administration is not EMIS's to remove."""
    sixth = manual(6, dt.time(16, 40), dt.time(18, 0), [1, 2, 3, 4, 5])

    merged = merge_emis_bells([sixth], bells_from_class_hours(FAKE_CLASS_HOURS))

    assert merged is not None
    assert [b.period for b in merged] == [1, 2, 3, 4, 5, 6]
    assert merged[-1] == sixth


def test_a_pair_that_left_emis_leaves_the_term() -> None:
    """ACA-4: bells an earlier sync took from EMIS follow EMIS."""
    current = bells_from_class_hours(FAKE_CLASS_HOURS)
    fewer = bells_from_class_hours(FAKE_CLASS_HOURS[:4])

    merged = merge_emis_bells(current, fewer)

    assert merged is not None and [b.period for b in merged] == [1, 2, 3, 4]


def test_a_changed_time_is_a_change() -> None:
    """ACA-4: EMIS moved the second pair by ten minutes."""
    current = bells_from_class_hours(FAKE_CLASS_HOURS)
    moved = [
        *FAKE_CLASS_HOURS[:1],
        EmisClassHour(1, dt.time(10, 20), dt.time(11, 40)),
        *FAKE_CLASS_HOURS[2:],
    ]

    merged = merge_emis_bells(current, bells_from_class_hours(moved))

    assert merged is not None and merged[1].start == dt.time(10, 20)
