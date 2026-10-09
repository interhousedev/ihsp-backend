"""Delete the files of old rejected and withdrawn materials (`library.purge`)."""

from datetime import timedelta
from functools import partial

from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi

REJECTED_AFTER = timedelta(days=30)
UNPUBLISHED_AFTER = timedelta(days=90)
BATCH = 200


class PurgeFiles:
    """Detach the files of the item and delete them; the item row keeps its history."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, files: FilesApi
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(self) -> int:
        """Return how many files were deleted (a rerun finds nothing left)."""
        now = self.clock.now()
        purged = 0
        async with self.uow_factory() as uow:
            ids = await uow.moderation.purgeable_items(
                rejected_before=now - REJECTED_AFTER,
                unpublished_before=now - UNPUBLISHED_AFTER,
                limit=BATCH,
            )
            for item in (await uow.items.get_many(ids)).values():
                for item_file in item.files:
                    await uow.items.remove_file(item.id, item_file.file_id)
                    await uow.pages.delete(item.id, item_file.file_id)
                    uow.after_commit(partial(self.files.delete_file, item_file.file_id))
                    purged += 1
                item.files = []
                item.has_text = False
                await uow.items.save(item)
            await uow.commit()
        return purged
