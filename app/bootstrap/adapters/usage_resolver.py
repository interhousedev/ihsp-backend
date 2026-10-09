"""UsageResolver for the files module, answered by links and AI."""

from collections.abc import Sequence
from typing import Literal, Protocol, cast
from uuid import UUID

from app.modules.files.domain.used_by import UsedBy


class LinkUsage(Protocol):
    """What the links module offers (LinksApiImpl)."""

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return (kind, id, label) per file."""
        ...


class ChatUsage(Protocol):
    """What the AI module offers (AiQueriesImpl)."""

    async def chats_using_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[UUID, str]]]:
        """Return (chat_id, title) per file."""
        ...


class NotebookUsage(Protocol):
    """What the notebooks module offers (NotebooksQueriesImpl)."""

    async def used_by_files(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        """Return (kind, notebook_id, title) per file."""
        ...


class UsageResolverAdapter:
    """Files ← links + ai + notebooks: where a file is shown, shared or attached."""

    def __init__(
        self,
        links: LinkUsage,
        ai: ChatUsage,
        notebooks: NotebookUsage | None = None,
    ) -> None:
        """Keep the providers (they may be lazy proxies)."""
        self._links = links
        self._ai = ai
        self._notebooks = notebooks

    async def used_by(self, file_ids: Sequence[UUID]) -> dict[UUID, list[UsedBy]]:
        """Return the places that refer to each file (missing key = unused)."""
        if not file_ids:
            return {}
        used: dict[UUID, list[UsedBy]] = {}
        for file_id, items in (await self._links.used_by_files(file_ids)).items():
            for kind, item_id, label in items:
                used.setdefault(file_id, []).append(
                    UsedBy(
                        kind=cast(Literal["link", "lesson", "chat", "notebook"], kind),
                        id=item_id,
                        label=label,
                    )
                )
        for file_id, chats in (await self._ai.chats_using_files(file_ids)).items():
            for chat_id, title in chats:
                used.setdefault(file_id, []).append(
                    UsedBy(kind="chat", id=chat_id, label=title)
                )
        for file_id, books in (await self._notebook_uses(file_ids)).items():
            for _, notebook_id, title in books:
                used.setdefault(file_id, []).append(
                    UsedBy(kind="notebook", id=notebook_id, label=title)
                )
        return used

    async def _notebook_uses(
        self, file_ids: Sequence[UUID]
    ) -> dict[UUID, list[tuple[str, UUID, str]]]:
        if self._notebooks is None:
            return {}
        return await self._notebooks.used_by_files(file_ids)
