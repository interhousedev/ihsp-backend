"""A librarian reads one book suggestion (the editor prefills a new book from it)."""

from uuid import UUID

from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.errors import SuggestionNotFoundError
from app.modules.library.domain.moderation_entities import BookSuggestion
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError


class GetSuggestion:
    """`GET /v1/manage/library/suggestions/{id}`."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, suggestion_id: UUID) -> BookSuggestion:
        """The suggestion, or `library/suggestion-not-found`."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        async with self.uow_factory() as uow:
            suggestion = await uow.moderation.get_suggestion(suggestion_id)
        if suggestion is None:
            raise SuggestionNotFoundError()
        return suggestion
