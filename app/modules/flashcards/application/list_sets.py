"""Use case: list the owner's sets with today's due and new counts (WEB-22)."""

from uuid import UUID

from app.modules.flashcards.application.set_views import SetViews
from app.modules.flashcards.application.views import SetItemView
from app.modules.flashcards.domain.flashcard_set import SetCounts
from app.modules.flashcards.domain.study import day_end
from app.modules.flashcards.ports.unit_of_work import UowFactory
from app.shared.clock import Clock


class ListSets:
    """Lists sets, newest first."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, views: SetViews
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.views = views

    async def execute(self, *, owner_id: UUID) -> list[SetItemView]:
        """Return `due_today` (seen cards due before the day ends) and `new_today`."""
        async with self.uow_factory() as uow:
            sets = await uow.sets.list_for_owner(owner_id)
            counts = await uow.cards.counts_for_sets(
                [s.id for s in sets], due_before=day_end(self.clock.now())
            )
        return [await self.views.item(s, counts.get(s.id, SetCounts())) for s in sets]
