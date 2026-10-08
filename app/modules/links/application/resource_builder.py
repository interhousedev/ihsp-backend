"""Turning links into views with titles, authors and files."""

from collections.abc import Sequence
from urllib.parse import urlsplit
from uuid import UUID

from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.views import LinkView, PersonView, ResourceView
from app.modules.links.domain.link import Link, LinkKind
from app.shared.contracts.files import FileRef, FilesApi
from app.shared.contracts.identity import IdentityDirectory

UNUSABLE_FILE_STATUSES = frozenset({"deleted", "rejected"})


def link_title(link: Link, file: FileRef | None) -> str:
    """Name shown for a link: the file name, the page title or the host."""
    if file is not None:
        return file.name
    if link.title:
        return link.title
    if link.target_url:
        return urlsplit(link.target_url).hostname or link.target_url
    return link.slug


class ResourceBuilder:
    """Loads files and authors for many links in two batched calls."""

    def __init__(
        self, files: FilesApi, identity: IdentityDirectory, urls: LinkUrls
    ) -> None:
        """Store the contracts and the URL builder."""
        self.files = files
        self.identity = identity
        self.urls = urls

    async def files_of(self, links: Sequence[Link]) -> dict[UUID, FileRef]:
        """Return the files used by the links, by id."""
        ids = list({link.file_id for link in links if link.file_id is not None})
        if not ids:
            return {}
        return await self.files.get_many(ids)

    async def link_views(self, links: Sequence[Link]) -> list[LinkView]:
        """Build a LinkView for each link, in order."""
        files = await self.files_of(links)
        return [
            LinkView(
                link=link,
                url=self.urls.url_for(link),
                file=files.get(link.file_id) if link.file_id else None,
            )
            for link in links
        ]

    async def resources(self, links: Sequence[Link]) -> list[ResourceView]:
        """Build resource views; links whose file is gone are left out."""
        files = await self.files_of(links)
        users = await self.identity.get_users(list({link.owner_id for link in links}))
        views = []
        for link in links:
            file = files.get(link.file_id) if link.file_id else None
            if link.kind is LinkKind.FILE and (
                file is None or file.status in UNUSABLE_FILE_STATUSES
            ):
                continue
            user = users.get(link.owner_id)
            author = PersonView(
                id=link.owner_id,
                first_name=user.first_name if user else "",
                last_name=user.last_name if user else "",
            )
            views.append(
                ResourceView(
                    link=link,
                    short_url=self.urls.short_url(link.slug),
                    title=link_title(link, file),
                    author=author,
                    file=file,
                )
            )
        return views
