"""Bells that come from EMIS ``class-hours`` and how they join a term's own bells."""

from collections import Counter
from collections.abc import Iterable, Sequence

from app.modules.academic.domain.schedule.term import STUDY_WEEKDAYS, Bell
from app.shared.contracts.emis import EmisClassHour


def bells_from_class_hours(hours: Iterable[EmisClassHour]) -> list[Bell]:
    """EMIS pair ``n`` (0-based) is period ``n + 1`` on every study weekday.

    EMIS has no weekday in ``class-hours``, so Saturday gets the same bells.
    """
    return [
        Bell(
            period=hour.pair_number + 1,
            start=hour.begin_time,
            end=hour.end_time,
            weekdays=list(STUDY_WEEKDAYS),
            source="emis",
        )
        for hour in sorted(hours, key=lambda item: item.pair_number)
    ]


def merge_emis_bells(
    current: Sequence[Bell], from_emis: Sequence[Bell]
) -> list[Bell] | None:
    """Return the term's bells after an EMIS sync, or None when nothing changes.

    EMIS wins for the periods it lists; bells of other periods that Administration
    set by hand stay. Bells an earlier sync took from EMIS for periods EMIS no
    longer lists are dropped.
    """
    listed = {bell.period for bell in from_emis}
    kept = [b for b in current if b.source == "manual" and b.period not in listed]
    merged = sorted([*from_emis, *kept], key=lambda bell: bell.period)
    if _signatures(merged) == _signatures(current):
        return None
    return merged


def _signatures(bells: Iterable[Bell]) -> Counter[tuple[object, ...]]:
    return Counter(
        (b.period, b.start, b.end, tuple(sorted(b.weekdays)), b.source) for b in bells
    )
