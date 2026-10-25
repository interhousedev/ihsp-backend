"""Give a short-lived download URL after the access check (FILE-3)."""

from typing import Literal
from uuid import UUID

from app.modules.files.application.access import require_readable
from app.modules.files.application.download_links import DownloadLinks, DownloadUrl
from app.modules.files.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

Disposition = Literal["inline", "attachment"]


class GetDownloadUrl:
    """Presigned GET for the owner or an administrator."""

    def __init__(self, *, uow_factory: UowFactory, links: DownloadLinks) -> None:
        """Store the dependencies."""
        self._uow_factory = uow_factory
        self._links = links

    async def execute(
        self, actor: Actor, file_id: UUID, disposition: Disposition | None = None
    ) -> DownloadUrl:
        """Return the URL; ``inline`` is honoured only for PDFs and images."""
        async with self._uow_factory() as uow:
            file = require_readable(await uow.files.get(file_id), actor)
        inline = None if disposition is None else disposition == "inline"
        return await self._links.url_for(file, inline=inline)
