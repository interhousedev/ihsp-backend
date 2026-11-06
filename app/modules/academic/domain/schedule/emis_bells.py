"""Bells that come from EMIS ``class-hours`` and how they join a term's own bells."""

from collections import Counter
from collections.abc import Iterable, Sequence

from app.modules.academic.domain.schedule.school_days import SCHOOL_DAYS
from app.modules.academic.domain.schedule.term import Bell
from app.shared.contracts.emis import EmisClassHour


def bells_from_class_hours(hours: Iterable[EmisClassHour]) -> list[Bell]:
    """EMIS pair ``n`` (0-based) is period ``n + 1`` on every school day.

    EMIS has no weekday in ``class-hours``, so Monday to Friday get the same bells.
    """
    return [
        Bell(
            period=hour.pair_number + 1,
            start=hour.begin_time,
            end=hour.end_time,
            weekdays=list(SCHOOL_DAYS),
            source="emis",
        )
        for hour in sorted(hours, key=lambda item: item.pair_number)
    ]


def merge_emis_bells(
    current: Sequence[Bell], from_emis: Sequence[Bell]
) -> list[Bell] | None:
    """Return the term's bells after an EMIS sync, or None when nothing changes.

    EMIS gives the Monday to Friday defaults: a listed period takes the EMIS bell,
    replacing a ``manual`` one. A period with an ``override`` on a school day belongs
    to Administration on every day: all its rows stay, so a different Friday or a
    block removed from Friday survives; only the remembered EMIS time is refreshed.
    Weekend blocks are never EMIS's. Manual bells of periods EMIS does not list stay.
    Bells an earlier sync took from EMIS for periods EMIS no longer lists are dropped.
    """
    by_period = {bell.period: bell for bell in from_emis}
    overridden = {
        bell.period
        for bell in current
        if bell.source == "override" and set(bell.weekdays) & set(SCHOOL_DAYS)
    }
    merged: list[Bell] = []
    for bell in current:
        listed = by_period.get(bell.period)
        if bell.period in overridden and listed is not None:
            merged.append(
                bell.model_copy(
                    update={
                        "source": "override",
                        "emis_start": listed.start,
                        "emis_end": listed.end,
                    }
                )
            )
        elif bell.source == "manual" and listed is None:
            merged.append(bell)
        elif bell.source == "override":  # EMIS dropped the period: it is Admin's now
            merged.append(bell.model_copy(update={"source": "manual"}))
        elif weekend := [day for day in bell.weekdays if day not in SCHOOL_DAYS]:
            merged.append(
                bell.model_copy(update={"weekdays": weekend, "source": "manual"})
            )
    merged.extend(bell for bell in from_emis if bell.period not in overridden)
    merged.sort(key=lambda bell: (bell.period, min(bell.weekdays)))
    if _signatures(merged) == _signatures(current):
        return None
    return merged


def _signatures(bells: Iterable[Bell]) -> Counter[tuple[object, ...]]:
    return Counter(
        (
            b.period,
            b.start,
            b.end,
            tuple(sorted(b.weekdays)),
            b.source,
            b.emis_start,
            b.emis_end,
        )
        for b in bells
    )
