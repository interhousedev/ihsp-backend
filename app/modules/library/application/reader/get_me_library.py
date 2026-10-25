"""Use case: the My library overview (LIB-8, LIB-9)."""

from app.modules.library.application.cards import CardBuilder
from app.modules.library.application.reader.views import MeLibraryView
from app.modules.library.application.views import ItemCardView
from app.modules.library.domain.access import can_read_content
from app.modules.library.domain.enums import ShelfState
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor

CONTINUE_COUNT = 6
SCAN_WINDOW = 30
MAX_WINDOWS = 3


class GetMeLibrary:
    """Continue reading, shelf counts and the offline limits of the device."""

    def __init__(
        self, *, uow_factory: UowFactory, cards: CardBuilder, settings: LibrarySettings
    ) -> None:
        """Store the unit of work factory, the card builder and the settings."""
        self.uow_factory = uow_factory
        self.cards = cards
        self.settings = settings

    async def execute(self, actor: Actor, *, locale: str) -> MeLibraryView:
        """The overview of the actor's own reading."""
        async with self.uow_factory() as uow:
            counts = await uow.shelf.counts(actor.user_id, listed_only=True)
            continue_cards = await self._continue_reading(uow, actor, locale)
        return MeLibraryView(
            continue_reading=continue_cards,
            shelf_counts={state: counts.get(state, 0) for state in ShelfState},
            offline_max_items=self.settings.offline_max_items,
            offline_max_bytes=self.settings.offline_max_bytes,
        )

    async def _continue_reading(
        self, uow: LibraryUnitOfWork, actor: Actor, locale: str
    ) -> list[ItemCardView]:
        """The last unfinished items the actor may still open, newest first."""
        readable = []
        for window in range(MAX_WINDOWS):
            rows = await uow.progress.unfinished(
                actor.user_id, limit=SCAN_WINDOW, offset=window * SCAN_WINDOW
            )
            items = await uow.items.get_many([row.item_id for row in rows])
            readable += [
                items[row.item_id]
                for row in rows
                if row.item_id in items and can_read_content(items[row.item_id], actor)
            ]
            if len(readable) >= CONTINUE_COUNT or len(rows) < SCAN_WINDOW:
                break
        return await self.cards.build(
            uow, readable[:CONTINUE_COUNT], viewer=actor, locale=locale
        )
