"""A short-lived URL for the reader or a download (GET .../files/{fid}/url)."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from app.modules.library.application.catalogue.common import (
    anonymous_cards,
    load_visible,
)
from app.modules.library.domain.access import can_download, can_read_content
from app.modules.library.domain.catalogue_errors import DownloadNotAllowedError
from app.modules.library.domain.entities import ItemFile
from app.modules.library.domain.enums import ItemKind
from app.modules.library.domain.errors import ItemNotFoundError, NotSupportedError
from app.modules.library.ports.stats_recorder import StatsRecorder
from app.modules.library.ports.unit_of_work import UowFactory
from app.settings import LibrarySettings
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi

FALLBACK_CONTENT_TYPE = "application/octet-stream"


@dataclass(frozen=True, slots=True)
class FileUrlView:
    """`ItemFileUrl` of the TypeScript contract."""

    url: str
    expires_at: datetime
    content_type: str
    byte_size: int


class GetFileUrl:
    """Hand out a presigned URL after the rights and status checks (LIB-3)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        stats: StatsRecorder,
        clock: Clock,
        settings: LibrarySettings,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.stats = stats
        self.clock = clock
        self.settings = settings

    async def execute(
        self, actor: Actor | None, item_id: UUID, file_id: UUID, *, inline: bool
    ) -> FileUrlView:
        """A URL valid for `reader_url_seconds`; counts one open of the item."""
        cards = anonymous_cards(self.settings)
        async with self.uow_factory() as uow:
            item = await load_visible(uow, str(item_id), actor, cards=cards)
            if item.kind is ItemKind.EXTERNAL:
                raise NotSupportedError(support_details="external items have no files")
            stored = item.file(file_id)
            if stored is None or not can_read_content(
                item, actor, anonymous_cards=cards
            ):
                raise ItemNotFoundError(support_details=f"no file {file_id}")
            if not inline and not can_download(item, actor, anonymous_cards=cards):
                raise DownloadNotAllowedError(support_details="download is off")
        return await self._issue(actor, item_id, stored, inline=inline)

    async def _issue(
        self, actor: Actor | None, item_id: UUID, stored: ItemFile, *, inline: bool
    ) -> FileUrlView:
        ttl = self.settings.reader_url_seconds
        url = await self.files.download_url(
            stored.file_id, inline=inline, ttl_seconds=ttl
        )
        ref = await self.files.get(stored.file_id)
        await self.stats.opened(item_id, actor.user_id if actor else None)
        return FileUrlView(
            url=url,
            expires_at=self.clock.now() + timedelta(seconds=ttl),
            content_type=ref.content_type if ref else FALLBACK_CONTENT_TYPE,
            byte_size=stored.byte_size,
        )
