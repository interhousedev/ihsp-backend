"""Read a shared answer without logging in: `s.ihsu.uz/ai/m-{uuid}`."""

from app.modules.links.application.not_found_counter import NotFoundCounter
from app.modules.links.application.views import PublicMessageView
from app.modules.links.domain.errors import LinkGoneError, LinkNotFoundError
from app.modules.links.domain.link import LinkKind
from app.modules.links.ports.hit_counter import HitCounter
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.ai import AiQueries
from app.shared.openui.visual import keep_valid_blocks

PREFIX = "m-"


class GetPublicMessage:
    """Text and dates only; 404 unknown, revoked or disabled, 410 expired."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        ai: AiQueries,
        hits: HitCounter,
        not_found: NotFoundCounter,
        clock: Clock,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.ai = ai
        self.hits = hits
        self.not_found = not_found
        self.clock = clock

    async def execute(self, slug: str, *, ip: str | None) -> PublicMessageView:
        """Return the answer; blocks are validated again on every read."""
        link = None
        if slug.startswith(PREFIX) and len(slug) <= 64:
            async with self.uow_factory() as uow:
                link = await uow.links.get_by_slug(slug)
        if (
            link is None
            or link.kind is not LinkKind.MESSAGE
            or link.target_id is None
            or link.snapshot_seq is None
            or link.expires_at is None
            or link.is_revoked
            or link.is_disabled
        ):
            await self.not_found.count(ip)
            raise LinkNotFoundError()
        if link.expires_at <= self.clock.now():
            raise LinkGoneError()
        found = await self.ai.message_for_share(link.target_id, link.snapshot_seq)
        if found is None or found["owner_id"] != link.owner_id:
            await self.not_found.count(ip)
            raise LinkNotFoundError()
        await self.hits.hit(link.id)
        return PublicMessageView(
            text=keep_valid_blocks(str(found["text"])),
            created_at=link.created_at,
            expires_at=link.expires_at,
        )
