"""Audience key matching for lessons of the same subject (ACA-6)."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys


def expand_for_overlap(keys: Iterable[str]) -> list[str]:
    """Keys a lesson with the given audience shares students with.

    A whole-group key matches the group and both of its subgroups; a subgroup
    key matches the group and that subgroup.
    """
    out: set[str] = set()
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        base = str(group_id)
        out.add(base)
        if subgroup is None:
            out.update((f"{base}:1", f"{base}:2"))
        else:
            out.add(f"{base}:{subgroup}")
    return sorted(out)


def group_keys(group_id: UUID) -> list[str]:
    """Every audience key that involves the group."""
    base = str(group_id)
    return [base, f"{base}:1", f"{base}:2"]
