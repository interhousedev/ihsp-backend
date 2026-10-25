"""List the caller's links and shares (SL-7, SHR-6)."""

from uuid import UUID

from app.modules.links.application.cursors import decode_id_cursor, encode_id_cursor
from app.modules.links.application.resource_builder import ResourceBuilder
from app.modules.links.application.views import LinkPage
from app.modules.links.domain.link import LinkKind
from app.modules.links.ports.unit_of_work import UowFactory
from app.shared.actor import Actor

MAX_LIMIT = 100


class ListMyLinks:
    """Page through the owner's links, newest first."""

    def __init__(self, *, uow_factory: UowFactory, builder: ResourceBuilder) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.builder = builder

    async def execute(
        self,
        actor: Actor,
        *,
        kind: LinkKind | None = None,
        target_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 20,
    ) -> LinkPage:
        """Return one page; deleted short links are not listed."""
        size = max(1, min(limit, MAX_LIMIT))
        before = decode_id_cursor(cursor)
        async with self.uow_factory() as uow:
            rows = await uow.links.list_by_owner(
                actor.user_id,
                kind=kind,
                target_id=target_id,
                before_id=before,
                limit=size + 1,
            )
        page = rows[:size]
        more = len(rows) > size
        return LinkPage(
            items=await self.builder.link_views(page),
            next_cursor=encode_id_cursor(page[-1].id) if more and page else None,
        )
