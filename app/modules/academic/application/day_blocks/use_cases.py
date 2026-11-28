"""Admin management of the non-lesson blocks and the student's view of them."""

import datetime as dt
from dataclasses import replace
from uuid import UUID

from app.modules.academic.application.day_blocks.ports import DayBlockStore
from app.modules.academic.application.schedule.common import today
from app.modules.academic.application.schedule.date_range import resolve_range
from app.modules.academic.domain.day_blocks import (
    DayBlock,
    DayBlockKind,
    DayBlockNotFoundError,
    DayBlockOccurrence,
    DayBlockScope,
    occurrences,
)
from app.shared.clock import Clock
from app.shared.ids import new_id


class ListDayBlocks:
    """Every block (admin)."""

    def __init__(self, store: DayBlockStore) -> None:
        """Store the dependencies."""
        self.store = store

    async def execute(self) -> list[DayBlock]:
        """Return the blocks ordered by start time."""
        return await self.store.list_all()


class CreateDayBlock:
    """Add a block (admin)."""

    def __init__(self, store: DayBlockStore) -> None:
        """Store the dependencies."""
        self.store = store

    async def execute(
        self,
        *,
        name: str,
        kind: DayBlockKind,
        starts_at: dt.time,
        ends_at: dt.time,
        weekdays: list[int],
        scope: DayBlockScope,
        course: int | None,
        group_ids: list[UUID],
    ) -> DayBlock:
        """Validate and save the new block."""
        block = DayBlock(
            new_id(),
            name,
            kind,
            starts_at,
            ends_at,
            weekdays,
            scope,
            course,
            group_ids,
        )
        block.validate()
        await self.store.save(block)
        return block


class UpdateDayBlock:
    """Replace the fields of a block (admin)."""

    def __init__(self, store: DayBlockStore) -> None:
        """Store the dependencies."""
        self.store = store

    async def execute(
        self,
        block_id: UUID,
        *,
        name: str,
        kind: DayBlockKind,
        starts_at: dt.time,
        ends_at: dt.time,
        weekdays: list[int],
        scope: DayBlockScope,
        course: int | None,
        group_ids: list[UUID],
    ) -> DayBlock:
        """Validate and save; DayBlockNotFoundError for an unknown id."""
        current = await self.store.get(block_id)
        if current is None:
            raise DayBlockNotFoundError()
        block = replace(
            current,
            name=name,
            kind=kind,
            starts_at=starts_at,
            ends_at=ends_at,
            weekdays=weekdays,
            scope=scope,
            course=course,
            group_ids=group_ids,
        )
        block.validate()
        await self.store.save(block)
        return block


class DeleteDayBlock:
    """Remove a block (admin)."""

    def __init__(self, store: DayBlockStore) -> None:
        """Store the dependencies."""
        self.store = store

    async def execute(self, block_id: UUID) -> None:
        """Delete; DayBlockNotFoundError for an unknown id."""
        if not await self.store.delete(block_id):
            raise DayBlockNotFoundError()


class GetStudentDayBlocks:
    """The blocks of the student's group on each date of a range."""

    def __init__(self, store: DayBlockStore, clock: Clock) -> None:
        """Store the dependencies."""
        self.store = store
        self.clock = clock

    async def execute(
        self, user_id: UUID, start: dt.date | None, end: dt.date | None
    ) -> list[DayBlockOccurrence]:
        """Same range rules as the timetable; empty for a student without a group."""
        first, last = resolve_range(start, end, today(self.clock))
        placement = await self.store.student_group(user_id)
        if placement is None:
            return []
        group_id, course = placement
        blocks = await self.store.list_all()
        return occurrences(blocks, first, last, group_id, course)
