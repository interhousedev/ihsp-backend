"""Counts of certificates by type, level and group."""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.custom_fields import FieldKind
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

NO_LEVEL = "—"
LEVEL_KEY = "level"


@dataclass(frozen=True, slots=True)
class GroupCounts:
    """How many entries of each level a group has."""

    group_id: UUID
    group_name: str
    counts: dict[str, int]


@dataclass(frozen=True, slots=True)
class TypeStats:
    """Levels of one type and the counts per group."""

    type_id: UUID
    levels: list[str]
    groups: list[GroupCounts]


class GetStaffStats:
    """Type by level by group, over the students the caller may see."""

    def __init__(self, *, uow_factory: UowFactory, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope

    async def execute(self, actor: Actor, flt: StaffFilters) -> list[TypeStats]:
        """Return stats for every type that has entries in scope."""
        students = await self._scope.students(actor, flt)
        by_id = {s.id: s for s in students}
        async with self._uow_factory() as uow:
            kinds = await uow.types.list_all()
            rows, _ = await uow.entries.query(
                repo_filter(students, flt), limit=None, offset=0
            )
        counters: dict[UUID, dict[UUID, Counter[str]]] = {}
        for row in rows:
            group = by_id[row.student_id].group_id
            per_group = counters.setdefault(row.type_id, {}).setdefault(
                group, Counter()
            )
            per_group[_level_of(row.custom_values) or NO_LEVEL] += 1
        names = {s.group_id: s.group_name for s in students}
        result = []
        for kind in kinds:
            groups = counters.get(kind.id)
            if not groups:
                continue
            seen = {level for counter in groups.values() for level in counter}
            order = _level_options(kind)
            levels = [lv for lv in order if lv in seen]
            levels += sorted(seen - set(levels) - {NO_LEVEL})
            levels += [NO_LEVEL] if NO_LEVEL in seen else []
            ordered = sorted(groups, key=lambda gid: names[gid].casefold())
            result.append(
                TypeStats(
                    type_id=kind.id,
                    levels=levels,
                    groups=[
                        GroupCounts(gid, names[gid], dict(groups[gid]))
                        for gid in ordered
                    ],
                )
            )
        return result


def _level_of(values: dict[str, object]) -> str | None:
    """The entry's level as text (a level is a single choice or text)."""
    value = values.get(LEVEL_KEY)
    return value if isinstance(value, str) and value else None


def _level_options(kind: CertificateType) -> list[str]:
    """The choices of the type's level field, in their defined order."""
    item = next((f for f in kind.custom_fields if f.key == LEVEL_KEY), None)
    if item is None or item.kind is not FieldKind.SINGLE:
        return []
    return list(item.options)
