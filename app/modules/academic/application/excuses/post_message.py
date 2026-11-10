"""Use case: a line in the thread of an excuse."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.academic.application.excuses.access import ExcuseAccess
from app.modules.academic.application.excuses.notices import ExcuseNotices
from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUowFactory,
)
from app.modules.academic.application.excuses.views import ExcusePresenter, ExcuseView
from app.modules.academic.domain.excuses.attachments import check_attachments
from app.modules.academic.domain.excuses.errors import (
    ExcuseInvalidError,
    ExcuseNotFoundError,
)
from app.modules.academic.domain.excuses.excuse import (
    MESSAGE_MAX,
    ExcuseMessage,
    clean_text,
)
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.ids import new_id


class PostExcuseMessage:
    """The student, the curator and Administration write at any time."""

    def __init__(
        self,
        *,
        uow_factory: ExcuseUowFactory,
        clock: Clock,
        directory: ExcuseDirectory,
        access: ExcuseAccess,
        files: FilesApi,
        notices: ExcuseNotices,
        presenter: ExcusePresenter,
    ) -> None:
        """Store the ports."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.directory = directory
        self.access = access
        self.files = files
        self.notices = notices
        self.presenter = presenter

    async def execute(
        self,
        *,
        actor: Actor,
        excuse_id: UUID,
        body: str | None,
        file_ids: Sequence[UUID] = (),
    ) -> ExcuseView:
        """Append the message and tell the other side.

        Raises:
            ExcuseNotFoundError: no such excuse of the caller.
            ExcuseInvalidError: neither text nor a file, or the text is too long.
            ExcuseAttachmentError: a file is not the author's, ready and allowed.
        """
        text = (body or "").strip()
        if text:
            text = clean_text(text, MESSAGE_MAX, "body")
        elif not file_ids:
            raise ExcuseInvalidError(params={"field": "body"})
        found = await self.files.get_many(list(file_ids)) if file_ids else {}
        check_attachments(file_ids, found, actor.user_id)
        async with self.uow_factory() as uow:
            excuse = await uow.excuses.get(excuse_id)
            if excuse is None:
                raise ExcuseNotFoundError()
            await self.access.either_side(excuse, actor)
            message = ExcuseMessage(
                id=new_id(),
                excuse_id=excuse.id,
                author_id=actor.user_id,
                body=text,
                file_ids=tuple(file_ids),
                created_at=self.clock.now(),
            )
            await uow.excuses.add_message(message)
            people = await self.directory.people([actor.user_id])
            author = people.get(actor.user_id)
            await self.notices.message(
                uow, excuse, message, author.name if author else ""
            )
            await uow.commit()
            return await self.presenter.detail(uow, excuse)
