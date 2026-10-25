"""Replace the EMIS materials of every group in the chosen terms (admin re-sync)."""

import asyncio
from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.marks.ports.timetable_sync import (
    MaterialResync,
)
from app.modules.academic.application.marks.ports.unit_of_work import MarksUowFactory
from app.modules.academic.domain.schedule.fetchers import pick_fetchers
from app.modules.academic.domain.schedule.material_scope import MaterialScope
from app.shared.jobs import JobCancelled, job_progress, job_should_stop

import structlog

log = structlog.get_logger(__name__)


class ResyncMaterials:
    """Runs in the worker: two students per group read EMIS, a few groups at once."""

    def __init__(
        self,
        *,
        uow_factory: MarksUowFactory,
        materials: MaterialResync,
        group_concurrency: int = 3,
    ) -> None:
        """Store collaborators and how many groups are pulled in parallel."""
        self._uow_factory = uow_factory
        self._materials = materials
        self._concurrency = max(group_concurrency, 1)

    async def execute(
        self,
        terms: Sequence[tuple[str, int]] | None,
        *,
        scope: MaterialScope | None = None,
        group_id: UUID | None = None,
    ) -> int:
        """Re-import the materials of ``terms`` (academic year, half) for all groups.

        ``terms`` None means the current term. A ``scope`` limits the pull to one
        subject (and teacher), ``group_id`` to one group.
        """
        if terms is not None and not terms:
            return 0
        chosen = None if terms is None else set(terms)
        groups = await self._groups(group_id)
        gate = asyncio.Semaphore(self._concurrency)
        done = 0
        await job_progress(done=0, total=len(groups))  # admin Processes

        async def one(each: UUID, people: list[tuple[UUID, int | None]]) -> int:
            nonlocal done
            async with gate:
                if await job_should_stop():
                    return 0
                try:
                    return await self._materials.resync_materials(
                        group_id=each,
                        terms=chosen,
                        fetchers=pick_fetchers(people),
                        scope=scope,
                    )
                except Exception:
                    log.warning(
                        "materials_resync_failed", group_id=str(each), exc_info=True
                    )
                    return 0
                finally:
                    done += 1
                    await job_progress(done=done)

        counts = await asyncio.gather(*(one(*group) for group in groups.items()))
        total = sum(counts)
        log.info("materials_resynced", groups=len(groups), resources=total)
        if await job_should_stop():
            raise JobCancelled()
        return total

    async def _groups(
        self, group_id: UUID | None
    ) -> dict[UUID, list[tuple[UUID, int | None]]]:
        """The synced students by group (only ``group_id`` when given)."""
        async with self._uow_factory() as uow:
            members = await uow.students.list_sync_members()
        groups: dict[UUID, list[tuple[UUID, int | None]]] = {}
        for user_id, member_group, subgroup in members:
            if group_id is None or member_group == group_id:
                groups.setdefault(member_group, []).append((user_id, subgroup))
        return groups
