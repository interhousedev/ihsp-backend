"""Mark identity and diffing (SYNC-5): EMIS gives marks no IDs."""

from collections import Counter
from collections.abc import Collection, Iterable, Sequence
from datetime import date
from typing import NamedTuple

from app.shared.contracts.emis import EmisMark, EmisMarkType


class MarkKey(NamedTuple):
    """Natural key of a mark inside one (student, subject, semester)."""

    type: EmisMarkType
    date: date
    value: int
    ordinal: int


def with_ordinals(marks: Iterable[EmisMark]) -> list[MarkKey]:
    """Number identical marks of one day: 1, 2, ... in input order."""
    seen: Counter[tuple[EmisMarkType, date, int]] = Counter()
    keys: list[MarkKey] = []
    for mark in marks:
        base = (mark.type, mark.date, mark.value)
        seen[base] += 1
        keys.append(MarkKey(mark.type, mark.date, mark.value, seen[base]))
    return keys


def diff(
    stored: Collection[MarkKey], fresh: Sequence[MarkKey]
) -> tuple[list[MarkKey], list[MarkKey]]:
    """Compare stored active keys with the fresh response: (added, removed)."""
    stored_set = set(stored)
    fresh_set = set(fresh)
    added = [key for key in fresh if key not in stored_set]
    removed = sorted(stored_set - fresh_set)
    return added, removed


def split_restored(
    added: Sequence[MarkKey], removed_before: Collection[MarkKey]
) -> tuple[list[MarkKey], list[MarkKey]]:
    """Split added keys into (really new, restored): a restored mark is silent."""
    previously_removed = set(removed_before)
    new = [key for key in added if key not in previously_removed]
    restored = [key for key in added if key in previously_removed]
    return new, restored
