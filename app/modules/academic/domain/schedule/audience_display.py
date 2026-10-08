"""Readable audience: "2TN2" for a whole group, "2TN1/2" for a subgroup."""

from collections.abc import Iterable, Mapping
from typing import Any
from uuid import UUID

from app.modules.academic.domain import audience as audience_keys


def audience_group_ids(keys: Iterable[str]) -> set[UUID]:
    """Return the groups mentioned by audience keys."""
    return audience_keys.group_ids(keys)


def display_names(keys: Iterable[str], names: Mapping[UUID, str]) -> tuple[str, ...]:
    """Return one label per key, e.g. ("2TN1/2", "2TN2/2")."""
    labels: list[str] = []
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        name = names.get(group_id, str(group_id))
        labels.append(name if subgroup is None else f"{name}/{subgroup}")
    return tuple(labels)


def audience_items(
    keys: Iterable[str], names: Mapping[UUID, str]
) -> list[dict[str, Any]]:
    """Return AudienceItem dicts: group_id, group_name and subgroup."""
    items: list[dict[str, Any]] = []
    for key in keys:
        group_id, subgroup = audience_keys.parse(key)
        items.append(
            {
                "group_id": str(group_id),
                "group_name": names.get(group_id, str(group_id)),
                "subgroup": subgroup,
            }
        )
    return items


def keys_from_input(items: Iterable[tuple[UUID, int | None]]) -> list[str]:
    """Build sorted unique audience keys from (group_id, subgroup) pairs."""
    return sorted({audience_keys.key(group_id, sub) for group_id, sub in items})
