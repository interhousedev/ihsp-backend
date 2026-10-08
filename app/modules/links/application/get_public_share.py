"""Read a shared chat or flash card set without logging in (SHR-2, SHR-4, SHR-6)."""

from typing import Any

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.views import (
    CardShareView,
    ChatShareView,
    PublicShareView,
)
from app.modules.links.domain.errors import (
    LinkDisabledError,
    LinkGoneError,
    LinkNotFoundError,
)
from app.modules.links.domain.link import Link, LinkKind, LinkState, ShareMode
from app.modules.links.ports.hit_counter import HitCounter
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.contracts.identity import IdentityDirectory

SHARE_PREFIXES = {"c-": LinkKind.CHAT, "f-": LinkKind.FLASHCARD_SET}


class GetPublicShare:
    """Return the content behind `s.ihsu.uz/ai/{slug}`."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        ai: AiQueries,
        flashcards: FlashcardsApi,
        identity: IdentityDirectory,
        hits: HitCounter,
        not_found: NotFoundCounter,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.ai = ai
        self.flashcards = flashcards
        self.identity = identity
        self.hits = hits
        self.not_found = not_found
        self.clock = clock

    async def execute(self, slug: str, *, ip: str | None) -> PublicShareView:
        """Return the share; 404 for unknown slugs, 410 for removed ones."""
        link = await self._find(slug, ip)
        state = link.state(self.clock.now())
        if state is LinkState.DISABLED:
            raise LinkDisabledError()
        if state is LinkState.GONE:
            raise LinkGoneError()
        view = await self._load(link)
        await self.hits.hit(link.id)
        return view

    async def _find(self, slug: str, ip: str | None) -> Link:
        expected = next(
            (
                kind
                for prefix, kind in SHARE_PREFIXES.items()
                if slug.startswith(prefix)
            ),
            None,
        )
        link = None
        if expected is not None:
            async with self.uow_factory() as uow:
                link = await uow.links.get_by_slug(slug)
        if link is None or link.kind is not expected or link.target_id is None:
            await self.not_found.count(ip)
            raise LinkNotFoundError()
        return link

    async def _load(self, link: Link) -> PublicShareView:
        assert link.target_id is not None
        users = await self.identity.get_users([link.owner_id])
        owner = users.get(link.owner_id)
        author = owner.first_name if owner else ""
        if link.kind is LinkKind.CHAT:
            until = link.snapshot_seq if link.share_mode is ShareMode.SNAPSHOT else None
            data = await self.ai.chat_for_share(link.target_id, until)
            if data is None:
                raise LinkGoneError()
            return _chat_view(link, author, data)
        found = await self.flashcards.get_set(link.target_id, None)
        if found is None:
            raise LinkGoneError()
        return _cards_view(link, author, found)


def _chat_view(link: Link, author: str, data: dict[str, Any]) -> PublicShareView:
    messages = tuple(
        ChatShareView(
            role="assistant" if item["role"] == "assistant" else "user",
            text=str(item.get("text", "")),
            tool_notes=tuple(str(note) for note in item.get("tool_notes", [])),
        )
        for item in data.get("messages", [])
    )
    return PublicShareView(
        kind="chat",
        title=str(data.get("title", "")),
        author_first_name=author,
        created_at=link.created_at,
        chat=messages,
        flashcards=None,
    )


def _cards_view(link: Link, author: str, data: dict[str, Any]) -> PublicShareView:
    cards = tuple(
        CardShareView(
            id=str(card["id"]), front=str(card["front"]), back=str(card["back"])
        )
        for card in data.get("cards", [])
    )
    return PublicShareView(
        kind="flashcard_set",
        title=str(data.get("title", "")),
        author_first_name=author,
        created_at=link.created_at,
        chat=None,
        flashcards=cards,
    )
