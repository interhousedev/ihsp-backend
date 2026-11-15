"""The job `library.backfill_covers`: covers for books uploaded without one."""

from uuid import UUID

from app.modules.library.application.catalogue.common import require_librarian
from app.modules.library.application.catalogue.cover_service import make_cover
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi
from app.shared.tasks import TaskKicker

BATCH = 50
TASK = "library.backfill_covers"


class BackfillCovers:
    """Idempotent: a book that got a cover (or has one) is never touched again."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        files: FilesApi,
        clock: Clock,
        kicker: TaskKicker,
    ) -> None:
        """Store the collaborators."""
        self.uow_factory = uow_factory
        self.files = files
        self.clock = clock
        self.kicker = kicker

    async def request(self, actor: Actor) -> None:
        """A librarian starts the job in the background."""
        require_librarian(actor)
        await self.kicker.kick(TASK)

    async def execute(self, *, limit: int = 500) -> int:
        """Try at most `limit` books without a cover; the number that got one."""
        made = 0
        tried = 0
        after: UUID | None = None
        while tried < limit:
            async with self.uow_factory() as uow:
                ids = await uow.items.ids_without_cover(
                    after=after, limit=min(BATCH, limit - tried)
                )
            if not ids:
                break
            for item_id in ids:
                made += await self._one(item_id)
            tried += len(ids)
            after = ids[-1]
        return made

    async def _one(self, item_id: UUID) -> int:
        async with self.uow_factory() as uow:
            item = await uow.items.get(item_id, lock=True)
            primary = (
                next((f for f in item.files if f.is_primary), None) if item else None
            )
            if item is None or primary is None:
                return 0
            if not await make_cover(self.files, item, primary):
                return 0
            item.updated_at = self.clock.now()
            await uow.items.save(item)
            await uow.commit()
        return 1
