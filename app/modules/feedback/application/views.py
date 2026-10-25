"""Read models of feedback for the HTTP API and the bot."""

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime
from uuid import UUID

from app.modules.feedback.domain.feedback import (
    Delivery,
    Feedback,
    FeedbackResponse,
)
from app.modules.feedback.ports.people import PeopleDirectory, Person
from app.shared.contracts.files import FileRef, FilesApi

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
class ResponseView:
    """An administrator's response."""

    id: UUID
    text: str
    attachments: list[AttachmentView]
    channels: list[str]
    deliveries: list[Delivery]
    author_name: str
    created_at: datetime


@dataclass(frozen=True, slots=True)
class FeedbackView:
    """A feedback item; ``reporter`` and ``responses`` only where asked for."""

    item: Feedback
    attachments: list[AttachmentView]
    reporter: Person | None = None
    responses: list[ResponseView] = field(default_factory=list)


class FeedbackPresenter:
    """Resolves file metadata, download URLs and names."""

    def __init__(self, *, files: FilesApi, people: PeopleDirectory) -> None:
        """Store the ports."""
        self._files = files
        self._people = people

    async def attachments(self, file_ids: Sequence[UUID]) -> list[AttachmentView]:
        """Views of the files that still exist, in the given order."""
        found = await self._files.get_many(list(file_ids)) if file_ids else {}
        return [
            await self._attachment(found[file_id])
            for file_id in file_ids
            if file_id in found
        ]

    async def _attachment(self, ref: FileRef) -> AttachmentView:
        url = await self._files.download_url(ref.id, ttl_seconds=DOWNLOAD_TTL_SECONDS)
        return AttachmentView(
            file_id=ref.id,
            name=ref.name,
            mime=ref.content_type,
            size=ref.byte_size,
            download_url=url,
        )

    async def items(
        self, items: Sequence[Feedback], *, with_reporter: bool = False
    ) -> list[FeedbackView]:
        """List views (no responses)."""
        reporters: dict[UUID, Person] = {}
        if with_reporter and items:
            reporters = await self._people.people(
                list({item.reporter_id for item in items})
            )
        return [
            FeedbackView(
                item=item,
                attachments=await self.attachments(item.attachment_file_ids),
                reporter=(
                    _reporter(item.reporter_id, reporters) if with_reporter else None
                ),
            )
            for item in items
        ]

    async def detail(
        self,
        item: Feedback,
        responses: Sequence[FeedbackResponse],
        *,
        with_reporter: bool = False,
    ) -> FeedbackView:
        """One item with its responses."""
        ids = {r.author_id for r in responses}
        if with_reporter:
            ids.add(item.reporter_id)
        people = await self._people.people(list(ids)) if ids else {}
        return FeedbackView(
            item=item,
            attachments=await self.attachments(item.attachment_file_ids),
            reporter=_reporter(item.reporter_id, people) if with_reporter else None,
            responses=[await self.response(r, people) for r in responses],
        )

    async def response(
        self, response: FeedbackResponse, people: dict[UUID, Person]
    ) -> ResponseView:
        """View of one response."""
        author = people.get(response.author_id)
        return ResponseView(
            id=response.id,
            text=response.text,
            attachments=await self.attachments(response.attachment_file_ids),
            channels=[channel.value for channel in response.channels],
            deliveries=list(response.deliveries),
            author_name=author.display_name if author else "",
            created_at=response.created_at,
        )


def _reporter(user_id: UUID, people: dict[UUID, Person]) -> Person:
    """The reporter, or a placeholder for a deleted account."""
    return people.get(user_id) or Person(
        user_id=user_id, display_name="", roles=(), locale="ru"
    )
