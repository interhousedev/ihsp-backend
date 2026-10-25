"""The signed-in person's book suggestions and their statuses ("My suggestions")."""

from app.modules.library.domain.moderation_entities import BookSuggestion
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

LIMIT = 100


class ListMySuggestions:
    """`GET /v1/library/suggestions/mine`: newest first, at most 100."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor) -> list[BookSuggestion]:
        """Only the actor's own suggestions."""
        async with self.uow_factory() as uow:
            return await uow.moderation.user_suggestions(actor.user_id, limit=LIMIT)
