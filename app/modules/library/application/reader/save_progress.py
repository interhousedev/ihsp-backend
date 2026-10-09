"""Use case: remember where the reader stopped (LIB-6, LIB-9)."""

from collections.abc import Mapping
from datetime import datetime
from typing import Any
from uuid import UUID

from app.modules.library.application.reader.access import (
    load_readable_item,
    require_file,
)
from app.modules.library.domain.reader_locator import validate_locator
from app.modules.library.domain.reader_progress import apply_progress
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class SaveProgress:
    """Store the reading position; the report with the latest `client_ts` wins."""

    def __init__(self, *, uow_factory: UowFactory, clock: Clock) -> None:
        """Store the unit of work factory and the clock."""
        self.uow_factory = uow_factory
        self.clock = clock

    async def execute(
        self,
        actor: Actor,
        item_id: UUID,
        *,
        file_id: UUID,
        locator: Mapping[str, Any],
        percent: float,
        client_ts: datetime,
        seconds_read: int | None,
    ) -> None:
        """Save the position of the actor in the item (books and materials only)."""
        async with self.uow_factory() as uow:
            item = await load_readable_item(uow, actor, item_id)
            item_file = require_file(item, file_id)
            updated = apply_progress(
                await uow.progress.get(actor.user_id, item_id),
                user_id=actor.user_id,
                item_id=item_id,
                file_id=file_id,
                locator=validate_locator(locator, item_file.format),
                percent=percent,
                client_ts=client_ts,
                seconds_read=seconds_read,
                now=self.clock.now(),
            )
            if updated is not None:
                await uow.progress.save(updated)
                await uow.commit()
