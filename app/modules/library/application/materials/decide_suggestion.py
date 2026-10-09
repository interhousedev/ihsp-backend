"""A librarian accepts or declines a book suggestion (LIB-2)."""

from uuid import UUID

from app.modules.library.application.materials.audit_types import SUGGESTION
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.enums import SuggestionStatus
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    SuggestionNotFoundError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.base_error import ForbiddenError
from app.shared.notifications import AuditDraft


class DecideSuggestion:
    """New -> accepted or declined, once; the decision is audited."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory

    async def execute(self, actor: Actor, suggestion_id: UUID, *, accept: bool) -> None:
        """Record the decision; the librarian adds the book by hand if accepted."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        async with self.uow_factory() as uow:
            suggestion = await uow.moderation.get_suggestion(suggestion_id)
            if suggestion is None:
                raise SuggestionNotFoundError()
            if suggestion.status is not SuggestionStatus.NEW:
                raise InvalidTransitionError(
                    params={"status": suggestion.status.value, "action": "decide"}
                )
            suggestion.status = (
                SuggestionStatus.ACCEPTED if accept else SuggestionStatus.DECLINED
            )
            suggestion.handled_by = actor.user_id
            await uow.moderation.save_suggestion(suggestion)
            uow.audit(
                AuditDraft(
                    type=SUGGESTION,
                    user_id=suggestion.user_id,
                    actor_id=actor.user_id,
                    metadata={
                        "suggestion_id": str(suggestion.id),
                        "status": suggestion.status.value,
                    },
                )
            )
            await uow.commit()
