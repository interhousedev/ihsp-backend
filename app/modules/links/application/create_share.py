"""Share a chat or a flash card set with a public link (SHR-1, SHR-3, SHR-8)."""

from datetime import datetime
from uuid import UUID

from app.modules.links.application.link_creation_limit import LinkCreationLimit
from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.application.views import LinkView
from app.modules.links.domain.errors import (
    InvalidExpiryError,
    InvalidLinkTargetError,
    ShareNotAllowedError,
)
from app.modules.links.domain.link import SHARE_KINDS, Link, LinkKind, ShareMode
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.ai import AiQueries
from app.shared.contracts.flashcards import FlashcardsApi
from app.shared.ids import new_id


def last_seq(messages: list[dict[str, object]]) -> int:
    """Return the highest message seq, or the message count when seq is absent."""
    seqs = []
    for index, message in enumerate(messages, start=1):
        value = message.get("seq", index)
        seqs.append(value if isinstance(value, int) else index)
    return max(seqs, default=0)


class CreateShare:
    """Create `c-{uuid}` or `f-{uuid}` for the owner's chat or set."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        ai: AiQueries,
        flashcards: FlashcardsApi,
        allocator: SlugAllocator,
        limit: LinkCreationLimit,
        clock: Clock,
        urls: LinkUrls,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.ai = ai
        self.flashcards = flashcards
        self.allocator = allocator
        self.limit = limit
        self.clock = clock
        self.urls = urls

    async def execute(
        self,
        actor: Actor,
        *,
        kind: LinkKind,
        target_id: UUID,
        share_mode: ShareMode | None = None,
        expires_at: datetime | None = None,
    ) -> LinkView:
        """Check ownership, fix the snapshot point and save the share."""
        if kind not in SHARE_KINDS:
            raise InvalidLinkTargetError(params={"kind": kind.value})
        now = self.clock.now()
        if expires_at is not None and expires_at <= now:
            raise InvalidExpiryError()
        await self.limit.hit(actor.user_id)
        mode, snapshot = await self._check_target(actor, kind, target_id, share_mode)

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=kind,
                owner_id=actor.user_id,
                created_at=now,
                target_id=target_id,
                share_mode=mode,
                snapshot_seq=snapshot,
                expires_at=expires_at,
            )

        async with self.uow_factory() as uow:
            link = await self.allocator.add(uow, build, kind=kind)
            await uow.commit()
        return LinkView(link=link, url=self.urls.url_for(link))

    async def _check_target(
        self, actor: Actor, kind: LinkKind, target_id: UUID, mode: ShareMode | None
    ) -> tuple[ShareMode | None, int | None]:
        if kind is LinkKind.CHAT:
            return await self._check_chat(actor, target_id, mode)
        owner = await self.flashcards.set_owner(target_id)
        if owner != actor.user_id:
            raise ShareNotAllowedError(params={"target_id": str(target_id)})
        return None, None

    async def _check_chat(
        self, actor: Actor, chat_id: UUID, mode: ShareMode | None
    ) -> tuple[ShareMode, int | None]:
        if await self.ai.chat_owner(chat_id) != actor.user_id:
            raise ShareNotAllowedError(params={"target_id": str(chat_id)})
        shared = await self.ai.chat_for_share(chat_id, None)
        if shared is None:
            raise ShareNotAllowedError(params={"target_id": str(chat_id)})
        chosen = mode or ShareMode.SNAPSHOT
        if chosen is ShareMode.LIVE:
            return chosen, None
        return chosen, last_seq(list(shared["messages"]))
