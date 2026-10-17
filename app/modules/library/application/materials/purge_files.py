"""Delete files of old rejected materials and declined suggestions (`library.purge`)."""

from datetime import datetime, timedelta
from functools import partial
from uuid import UUID

from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi

REJECTED_AFTER = timedelta(days=30)
UNPUBLISHED_AFTER = timedelta(days=90)
DECLINED_SUGGESTION_AFTER = timedelta(days=30)
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
            purged += await self._purge_suggestions(uow, now)
            await uow.commit()
        return purged

    async def _purge_suggestions(self, uow: LibraryUnitOfWork, now: datetime) -> int:
        """The file and cover of suggestions declined more than 30 days ago."""
        purged = 0
        found = await uow.moderation.purgeable_suggestions(
            declined_before=now - DECLINED_SUGGESTION_AFTER, limit=BATCH
        )
        for suggestion in found:
            cover = (suggestion.details or {}).get("cover_file_id")
            for file_id in (suggestion.file_id, cover):
                if file_id is not None:
                    uow.after_commit(
                        partial(self.files.delete_file, UUID(str(file_id)))
                    )
                    purged += 1
            suggestion.file_id = None
            if suggestion.details is not None:
                suggestion.details = {**suggestion.details, "cover_file_id": None}
            await uow.moderation.save_suggestion(suggestion)
        return purged
