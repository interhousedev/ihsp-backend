"""A librarian turns a student's suggestion into a book (`/upload/` -> manage editor).

The librarian edits the suggested form in the book editor and saves it as a book
(`POST /manage/library/books`); approving then links that book to the suggestion,
attaches the suggester's file, credits the suggester in the book's history and
tells them.
"""

from uuid import UUID

from app.modules.library.application.catalogue.books.attach_book_file import (
    AttachBookFile,
)
from app.modules.library.application.materials.audit_types import SUGGESTION
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.enums import (
    EventKind,
    FileFormat,
    ItemKind,
    SuggestionStatus,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ItemNotFoundError,
    SuggestionNotFoundError,
)
from app.modules.library.domain.moderation_entities import BookSuggestion
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import SYSTEM_USER_ID, Actor
from app.shared.base_error import ForbiddenError
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.notifications import AuditDraft, NotificationDraft, NotificationType

_FORMATS = {"pdf": FileFormat.PDF, "epub": FileFormat.EPUB}


def suggestion_file_ids(suggestion: BookSuggestion) -> list[UUID]:
    """The suggested file and the cover named in the form."""
    ids = [suggestion.file_id] if suggestion.file_id else []
    cover = (suggestion.details or {}).get("cover_file_id")
    if cover is not None:
        ids.append(UUID(str(cover)))
    return ids


def format_of(content_type: str) -> FileFormat | None:
    """PDF or EPUB from the stored content type; anything else is not a book file."""
    for hint, file_format in _FORMATS.items():
        if hint in content_type:
            return file_format
    return None


class ApproveSuggestion:
    """New -> accepted, with the book it became; once."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        files: FilesApi,
        attach: AttachBookFile,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files
        self.attach = attach

    async def execute(
        self, actor: Actor, suggestion_id: UUID, *, item_id: UUID
    ) -> BookSuggestion:
        """Link the book, hand over the file and notify the suggester."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        async with self.uow_factory() as uow:
            suggestion = await self._new(uow, suggestion_id)
            item = await uow.items.get(item_id)
            if item is None or item.kind is not ItemKind.BOOK:
                raise ItemNotFoundError(support_details=f"no book {item_id}")
            attached = item.file(suggestion.file_id) if suggestion.file_id else None
        if suggestion.file_id is not None and attached is None:
            await self._attach_file(actor, suggestion, item_id)
        async with self.uow_factory() as uow:
            suggestion = await self._new(uow, suggestion_id)
            suggestion.status = SuggestionStatus.ACCEPTED
            suggestion.handled_by = actor.user_id
            suggestion.item_id = item_id
            suggestion.decided_at = self.clock.now()
            await uow.moderation.save_suggestion(suggestion)
            await uow.events.append(
                item_id,
                EventKind.EDITED,
                at=suggestion.decided_at,
                actor_id=actor.user_id,
                data={
                    "suggestion_id": str(suggestion.id),
                    "suggested_by": str(suggestion.user_id),
                },
            )
            uow.notify(
                NotificationDraft(
                    user_id=suggestion.user_id,
                    type=NotificationType.LIBRARY_SUGGESTION_APPROVED,
                    payload={
                        "suggestion_id": str(suggestion.id),
                        "item_id": str(item_id),
                        "title": item.title,
                    },
                    dedupe_key=f"library_suggestion_approved:{suggestion.id}",
                )
            )
            uow.audit(
                AuditDraft(
                    type=SUGGESTION,
                    user_id=suggestion.user_id,
                    actor_id=actor.user_id,
                    metadata={
                        "suggestion_id": str(suggestion.id),
                        "status": suggestion.status.value,
                        "item_id": str(item_id),
                    },
                )
            )
            await uow.commit()
        await self.files.transfer_ownership(
            suggestion_file_ids(suggestion), SYSTEM_USER_ID
        )
        return suggestion

    async def _new(self, uow: LibraryUnitOfWork, suggestion_id: UUID) -> BookSuggestion:
        suggestion = await uow.moderation.get_suggestion(suggestion_id)
        if suggestion is None:
            raise SuggestionNotFoundError()
        if suggestion.status is not SuggestionStatus.NEW:
            raise InvalidTransitionError(
                params={"status": suggestion.status.value, "action": "approve"}
            )
        return suggestion

    async def _attach_file(
        self, actor: Actor, suggestion: BookSuggestion, item_id: UUID
    ) -> None:
        assert suggestion.file_id is not None
        ref = await self.files.get(suggestion.file_id)
        file_format = format_of(ref.content_type) if ref else None
        if file_format is None:
            # Not a PDF or EPUB (or gone): the librarian attaches a file by hand.
            return
        await self.attach.execute(
            actor,
            item_id,
            file_id=suggestion.file_id,
            file_format=file_format,
            is_primary=True,
            uploaded_by=suggestion.user_id,
        )
