"""Students ranked by a type's score (or level order), or by their count."""

from collections import Counter
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.certificates.application.list_staff_entries import repo_filter
from app.modules.certificates.application.staff_scope import StaffFilters, StaffScope
from app.modules.certificates.domain.certificate_type import CertificateType
from app.modules.certificates.domain.entry import CertificateEntry
from app.modules.certificates.domain.errors import CertificateTypeNotFoundError
from app.modules.certificates.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

MAX_LIMIT = 200


@dataclass(frozen=True, slots=True)
class RankedStudent:
    """A student, their number of certificates, and their ranking value.

    ``value`` is the best score of the selected type (or its level's position
    in the level order when the type has no score); None without a type.
    """

    student_id: UUID
    name: str
    group_name: str
    count: int
    value: float | None = None


class GetStaffRanking:
    """Top students of the type by score, else by number of certificates."""

    def __init__(self, *, uow_factory: UowFactory, scope: StaffScope) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._scope = scope

    async def execute(
        self, actor: Actor, flt: StaffFilters, *, limit: int
    ) -> list[RankedStudent]:
        """Return up to ``limit`` students with a value (or a certificate)."""
        students = await self._scope.students(actor, flt)
        by_id = {s.id: s for s in students}
        kind: CertificateType | None = None
        async with self._uow_factory() as uow:
            if flt.type_id is not None:
                kind = await uow.types.get(flt.type_id)
                if kind is None:
                    raise CertificateTypeNotFoundError()
            rows, _ = await uow.entries.query(
                repo_filter(students, flt), limit=None, offset=0
            )
        counts: Counter[UUID] = Counter(row.student_id for row in rows)
        best: dict[UUID, float] = {}
        if kind is not None:
            for row in rows:
                value = _rank_value(kind, row)
                if value is None:
                    continue
                best[row.student_id] = max(value, best.get(row.student_id, value))
        ranked = [
            RankedStudent(
                sid, by_id[sid].name, by_id[sid].group_name, count, best.get(sid)
            )
            for sid, count in counts.items()
            if kind is None or sid in best
        ]
        ranked.sort(
            key=lambda r: (
                -(r.value or 0.0),
                -r.count,
                r.name.casefold(),
                str(r.student_id),
            )
        )
        return ranked[: max(1, min(limit, MAX_LIMIT))]


def _rank_value(kind: CertificateType, row: CertificateEntry) -> float | None:
    """The score, else the position of the level among the level choices."""
    values: dict[str, Any] = row.custom_values
    score = values.get("score")
    if isinstance(score, int | float) and not isinstance(score, bool):
        return float(score)
    level = values.get("level")
    item = next((f for f in kind.custom_fields if f.key == "level"), None)
    if isinstance(level, str) and item is not None and level in item.options:
        return float(item.options.index(level))
    return None
