"""Use case: replace the actor's page markup of an item."""

from collections.abc import Mapping, Sequence
from typing import Any
from uuid import UUID

from app.modules.library.application.reader.access import (
    load_readable_item,
    require_file,
)
from app.modules.library.domain.reader_markup import Markup, parse_pages
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock


class SaveMarkup:
    """Store the whole markup of the item; an empty one removes the row."""

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
        pages: Mapping[str, Sequence[Mapping[str, Any]]],
    ) -> Markup:
        """Replace the actor's markup; the rows are always the actor's own."""
        parsed = parse_pages(pages)
        async with self.uow_factory() as uow:
            item = await load_readable_item(uow, actor, item_id)
            require_file(item, file_id)
            markup = Markup(
                user_id=actor.user_id,
                item_id=item_id,
                file_id=file_id,
                pages=parsed,
                updated_at=self.clock.now(),
            )
            if parsed:
                await uow.markup.save(markup)
            else:
                await uow.markup.delete(actor.user_id, item_id)
            await uow.commit()
        return markup
