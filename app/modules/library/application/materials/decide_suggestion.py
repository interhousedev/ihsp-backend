"""A librarian accepts or declines a book suggestion (LIB-2)."""

from uuid import UUID

from app.modules.library.application.materials.approve_suggestion import (
    suggestion_file_ids,
)
from app.modules.library.application.materials.audit_types import SUGGESTION
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.enums import SuggestionStatus
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    SuggestionNotFoundError,
)
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import SYSTEM_USER_ID, Actor
from app.shared.base_error import ForbiddenError, ValidationFailedError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType

REASON_MAX = 1000


class DecideSuggestion:
    """New -> accepted or declined, once; the decision is audited."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, files: FilesApi
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(
        self,
        actor: Actor,
        suggestion_id: UUID,
        *,
        accept: bool,
        reason: str | None = None,
    ) -> None:
        """Record the decision; a decline tells the suggester why.

        Accepting here only marks it (the librarian adds the book by hand);
        `ApproveSuggestion` is the editor's approve that links the new book. The
        files of a declined suggestion are deleted after a retention (`PurgeFiles`).
        """
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        reason = (reason or "").strip() or None
        if reason is not None and len(reason) > REASON_MAX:
            raise ValidationFailedError(params={"field": "reason"})
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
            suggestion.decided_at = self.clock.now()
            if not accept:
                suggestion.reason = reason
                uow.notify(
                    NotificationDraft(
                        user_id=suggestion.user_id,
                        type=NotificationType.LIBRARY_SUGGESTION_DECLINED,
                        payload={
                            "suggestion_id": str(suggestion.id),
                            "title": suggestion.title,
                            "reason": reason,
                        },
                        dedupe_key=f"library_suggestion_declined:{suggestion.id}",
                    )
                )
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
        if accept:
            # The library keeps the book: out of the student's quota and reach.
            await self.files.transfer_ownership(
                suggestion_file_ids(suggestion), SYSTEM_USER_ID
            )
