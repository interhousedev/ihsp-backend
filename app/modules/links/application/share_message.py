"""Share one assistant answer with OpenUI blocks for seven days (bot visualization)."""

from datetime import timedelta
from uuid import UUID

from app.modules.links.application.link_creation_limit import LinkCreationLimit
from app.modules.links.application.link_urls import LinkUrls
from app.modules.links.application.slug_allocator import SlugAllocator
from app.modules.links.application.views import LinkView
from app.modules.links.domain.errors import ShareNotAllowedError
from app.modules.links.domain.link import Link, LinkKind
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.ai import AiQueries
from app.shared.ids import new_id
from app.shared.openui.blocks import split_blocks
from app.shared.openui.visual import has_valid_blocks

MESSAGE_SHARE_TTL = timedelta(days=7)
TITLE_CHARS = 80


def _title(text: str) -> str:
    """The first words of the answer's prose, for the owner's list of links."""
    prose = " ".join(p.text for p in split_blocks(text) if p.kind == "text")
    flat = " ".join(prose.replace("#", " ").replace("*", " ").split())
    return flat[:TITLE_CHARS]


class ShareMessage:
    """Create `m-{uuid}` for one answer of the owner's chat (chat id + seq)."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        ai: AiQueries,
        allocator: SlugAllocator,
        limit: LinkCreationLimit,
        clock: Clock,
        urls: LinkUrls,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.ai = ai
        self.allocator = allocator
        self.limit = limit
        self.clock = clock
        self.urls = urls

    async def execute(self, actor: Actor, *, chat_id: UUID, seq: int) -> LinkView:
        """Check the owner and the blocks, then save a share expiring in 7 days."""
        found = await self.ai.message_for_share(chat_id, seq)
        if (
            found is None
            or found["owner_id"] != actor.user_id
            or not has_valid_blocks(str(found["text"]))
        ):
            raise ShareNotAllowedError(params={"target_id": str(chat_id)})
        await self.limit.hit(actor.user_id)
        now = self.clock.now()
        title = _title(str(found["text"])) or None

        def build(slug: str) -> Link:
            return Link(
                id=new_id(),
                slug=slug,
                kind=LinkKind.MESSAGE,
                owner_id=actor.user_id,
                created_at=now,
                target_id=chat_id,
                snapshot_seq=seq,
                expires_at=now + MESSAGE_SHARE_TTL,
                title=title,
            )

        async with self.uow_factory() as uow:
            link = await self.allocator.add(uow, build, kind=LinkKind.MESSAGE)
            await uow.commit()
        return LinkView(link=link, url=self.urls.url_for(link))
