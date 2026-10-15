"""Replace the EMIS materials of every group in the chosen terms (admin re-sync)."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.marks.ports.timetable_sync import (
    MaterialResync,
)
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.schedule.fetchers import pick_fetchers

import structlog

log = structlog.get_logger(__name__)


class ResyncMaterials:
    """Runs in the worker: two students per group read EMIS, one group at a time."""

    def __init__(
        self, *, uow_factory: MarksUowFactory, materials: MaterialResync
    ) -> None:
        """Store collaborators."""
        self._uow_factory = uow_factory
        self._materials = materials

    async def execute(self, terms: Sequence[tuple[str, int]]) -> int:
        """Re-import the materials of ``terms`` (academic year, half) for all groups."""
        if not terms:
            return 0
        async with self._uow_factory() as uow:
            members = await uow.students.list_sync_members()
        groups: dict[UUID, list[tuple[UUID, int | None]]] = {}
        for user_id, group_id, subgroup in members:
            groups.setdefault(group_id, []).append((user_id, subgroup))
        total = 0
        for group_id, people in groups.items():
            try:
                total += await self._materials.resync_materials(
                    group_id=group_id,
                    terms=set(terms),
                    fetchers=pick_fetchers(people),
                )
            except Exception:
                log.warning(
                    "materials_resync_failed", group_id=str(group_id), exc_info=True
                )
        log.info("materials_resynced", groups=len(groups), resources=total)
        return total
