"""Counts of certificates by type, level and group, grouped by the starred field."""

from collections import Counter
from dataclasses import dataclass
from uuid import UUID

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.custom_fields import CustomField, FieldKind
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

NO_LEVEL = "—"
LEVEL_KEY = "level"


@dataclass(frozen=True, slots=True)
class GroupCounts:
    """How many entries of each value a group has, and the group's average."""

    group_id: UUID
    group_name: str
    counts: dict[str, int]
    average: float | None = None
    """The average of the starred number field (None for other fields)."""


@dataclass(frozen=True, slots=True)
class TypeStats:
    """Values of one type and the counts per group.

    The values are grouped by the starred field when the type has one, else by
    the level. ``primary_key`` and ``primary_kind`` are set only for a starred field.
    """

    type_id: UUID
    levels: list[str]
    groups: list[GroupCounts]
    primary_key: str | None = None
    primary_kind: FieldKind | None = None
    average: float | None = None
    """The average of the starred number field over the whole scope."""


class GetStaffStats:
    """Type by value by group, over the students the caller may see."""

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
        by_type = {kind.id: kind for kind in kinds}
        counters: dict[UUID, dict[UUID, Counter[str]]] = {}
        numbers: dict[UUID, dict[UUID, list[float]]] = {}
        for row in rows:
            kind = by_type.get(row.type_id)
            if kind is None:
                continue
            group = by_id[row.student_id].group_id
            label, number = _measure(kind, row.custom_values)
            per_group = counters.setdefault(row.type_id, {}).setdefault(
                group, Counter()
            )
            per_group[label] += 1
            if number is not None:
                numbers.setdefault(row.type_id, {}).setdefault(group, []).append(number)
        names = {s.group_id: s.group_name for s in students}
        result = []
        for kind in kinds:
            groups = counters.get(kind.id)
            if not groups:
                continue
            seen = {value for counter in groups.values() for value in counter}
            ordered = sorted(groups, key=lambda gid: names[gid].casefold())
            group_numbers = numbers.get(kind.id, {})
            starred = _starred(kind)
            result.append(
                TypeStats(
                    type_id=kind.id,
                    levels=_ordered_labels(kind, seen),
                    groups=[
                        GroupCounts(
                            gid,
                            names[gid],
                            dict(groups[gid]),
                            _mean(group_numbers.get(gid)),
                        )
                        for gid in ordered
                    ],
                    primary_key=starred.key if starred else None,
                    primary_kind=starred.kind if starred else None,
                    average=_mean(
                        [n for values in group_numbers.values() for n in values]
                    ),
                )
            )
        return result


def _starred(kind: CertificateType) -> CustomField | None:
    """The type's starred field, if it has one."""
    return next((f for f in kind.custom_fields if f.primary), None)


def _measure(
    kind: CertificateType, values: dict[str, object]
) -> tuple[str, float | None]:
    """The label an entry counts under, and its number when the star is a number."""
    starred = _starred(kind)
    if starred is None:
        return _level_of(values) or NO_LEVEL, None
    raw = values.get(starred.key)
    if starred.kind is FieldKind.NUMBER:
        if isinstance(raw, int | float) and not isinstance(raw, bool):
            return _number_label(float(raw)), float(raw)
        return NO_LEVEL, None
    return (raw if isinstance(raw, str) and raw else NO_LEVEL), None


def _number_label(value: float) -> str:
    """A number as its count label: 1200, not 1200.0."""
    return str(int(value)) if value.is_integer() else str(value)


def _level_of(values: dict[str, object]) -> str | None:
    """The entry's level as text (a level is a single choice or text)."""
    value = values.get(LEVEL_KEY)
    return value if isinstance(value, str) and value else None


def _ordered_labels(kind: CertificateType, seen: set[str]) -> list[str]:
    """Numbers ascending, else the defined choices, then the rest; the dash last."""
    starred = _starred(kind)
    if starred is not None and starred.kind is FieldKind.NUMBER:
        numbers = sorted((v for v in seen if v != NO_LEVEL), key=float)
        return numbers + ([NO_LEVEL] if NO_LEVEL in seen else [])
    order = _choice_options(kind)
    levels = [lv for lv in order if lv in seen]
    levels += sorted(seen - set(levels) - {NO_LEVEL})
    levels += [NO_LEVEL] if NO_LEVEL in seen else []
    return levels


def _choice_options(kind: CertificateType) -> list[str]:
    """The choices of the field the stats group by, in their defined order."""
    item = _starred(kind) or next(
        (f for f in kind.custom_fields if f.key == LEVEL_KEY), None
    )
    if item is None or item.kind is not FieldKind.SINGLE:
        return []
    return list(item.options)


def _mean(numbers: list[float] | None) -> float | None:
    """The average of the numbers, None when there are none."""
    return sum(numbers) / len(numbers) if numbers else None
