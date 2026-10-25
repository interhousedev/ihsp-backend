"""Account closure: delete the shelf, progress and annotations of the user (§ 8.1)."""

from uuid import UUID

from app.modules.library.ports.unit_of_work import UowFactory


class DeleteReaderData:
    """Everything private to the reader goes with the account (LIB-8, LIB-16)."""

    def __init__(self, *, uow_factory: UowFactory) -> None:
        """Store the unit of work factory."""
        self.uow_factory = uow_factory

    async def execute(self, user_id: UUID) -> int:
        """Returns how many rows were deleted (running it again deletes none)."""
        async with self.uow_factory() as uow:
            deleted = await uow.annotations.delete_all(user_id)
            deleted += await uow.progress.delete_all(user_id)
            deleted += await uow.shelf.delete_all(user_id)
            await uow.commit()
        return deleted
