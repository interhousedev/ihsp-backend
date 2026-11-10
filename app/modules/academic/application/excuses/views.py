"""Read models of excuses for the HTTP API, the bot and the journal."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from uuid import UUID

from app.modules.academic.application.excuses.ports import (
    ExcuseDirectory,
    ExcuseUnitOfWork,
    Person,
)
from app.modules.academic.domain.excuses.excuse import (
    Excuse,
    ExcuseMessage,
    ExcuseTemplate,
)
from app.shared.contracts.files import FilesApi

DOWNLOAD_TTL_SECONDS = 3600


@dataclass(frozen=True, slots=True)
class AttachmentView:
    """A stored file with a presigned download URL (valid one hour)."""

    file_id: UUID
    name: str
    mime: str
    size: int
    download_url: str


@dataclass(frozen=True, slots=True)
class MessageView:
    """A thread line with its author's name and files."""

    message: ExcuseMessage
    author_name: str
    attachments: list[AttachmentView]


@dataclass(frozen=True, slots=True)
class ExcuseView:
    """An excuse with its template and student; ``thread`` only on the detail."""

    excuse: Excuse
    template: ExcuseTemplate | None
    student_name: str
    thread: list[MessageView] = field(default_factory=list)


class ExcusePresenter:
    """Resolves templates, names and file URLs."""

    def __init__(self, *, files: FilesApi, directory: ExcuseDirectory) -> None:
        """Store the ports."""
        self._files = files
        self._directory = directory

    async def items(
        self, uow: ExcuseUnitOfWork, excuses: Sequence[Excuse]
    ) -> list[ExcuseView]:
        """List views (no thread)."""
        templates = {t.id: t for t in await uow.excuses.templates(active_only=False)}
        people = await self._directory.people(list({e.student_id for e in excuses}))
        return [
            ExcuseView(
                excuse=e,
                template=templates.get(e.template_id),
                student_name=_name(people, e.student_id),
            )
            for e in excuses
        ]

    async def detail(self, uow: ExcuseUnitOfWork, excuse: Excuse) -> ExcuseView:
        """One excuse with its thread."""
        (view,) = await self.items(uow, [excuse])
        messages = await uow.excuses.messages(excuse.id)
        people = await self._directory.people(list({m.author_id for m in messages}))
        thread = [
            MessageView(
                message=m,
                author_name=_name(people, m.author_id),
                attachments=await self._attachments(m.file_ids),
            )
            for m in messages
        ]
        return ExcuseView(
            excuse=view.excuse,
            template=view.template,
            student_name=view.student_name,
            thread=thread,
        )

    async def _attachments(self, file_ids: Sequence[UUID]) -> list[AttachmentView]:
        found = await self._files.get_many(list(file_ids)) if file_ids else {}
        views: list[AttachmentView] = []
        for file_id in file_ids:
            ref = found.get(file_id)
            if ref is None:
                continue
            url = await self._files.download_url(
                ref.id, ttl_seconds=DOWNLOAD_TTL_SECONDS
            )
            views.append(
                AttachmentView(
                    file_id=ref.id,
                    name=ref.name,
                    mime=ref.content_type,
                    size=ref.byte_size,
                    download_url=url,
                )
            )
        return views


def _name(people: dict[UUID, Person], user_id: UUID) -> str:
    person = people.get(user_id)
    return person.name if person is not None else ""
