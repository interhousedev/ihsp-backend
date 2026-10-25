"""Describing hand changes to a lesson as {field: [old, new]} (ACA-7)."""

import datetime as dt
from typing import Any

from app.shared.clock import to_local


def time_label(starts_at: dt.datetime, ends_at: dt.datetime) -> str:
    """Return the local time range, e.g. "09:55-10:40"."""
    start, end = to_local(starts_at), to_local(ends_at)
    return f"{start:%H:%M}-{end:%H:%M}"


def merge_changes(
    existing: dict[str, Any] | None, new: dict[str, list[Any]]
) -> dict[str, Any] | None:
    """Combine earlier changes with new ones, keeping each field's first old value.

    A field changed back to its original value disappears; no changes gives None.
    """
    merged: dict[str, Any] = dict(existing or {})
    for name, (old, value) in new.items():
        first_old = merged[name][0] if name in merged else old
        if first_old == value:
            merged.pop(name, None)
        else:
            merged[name] = [first_old, value]
    return merged or None
