"""Audience keys: '<group_id>' (whole group) and '<group_id>:<subgroup>'."""

from collections.abc import Iterable
from uuid import UUID


def key(group_id: UUID, subgroup: int | None) -> str:
    """Build one audience key."""
    return str(group_id) if subgroup is None else f"{group_id}:{subgroup}"


def parse(value: str) -> tuple[UUID, int | None]:
    """Split a key into (group_id, subgroup)."""
    group, _, sub = value.partition(":")
    return UUID(group), (int(sub) if sub else None)


def student_keys(group_id: UUID, subgroup: int | None) -> list[str]:
    """Keys a student matches; without a subgroup the student matches both."""
    base = str(group_id)
    if subgroup is None:
        return [base, f"{base}:1", f"{base}:2"]
    return [base, f"{base}:{subgroup}"]


def group_ids(keys: Iterable[str]) -> set[UUID]:
    """Groups mentioned by a set of keys."""
    return {parse(k)[0] for k in keys}
