"""Account closure: withdraw the unfinished materials of the user (doc § 8.1)."""

from functools import partial
from uuid import UUID

from app.modules.library.domain.enums import EventKind, ItemStatus, StatusReasonCode
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.clock import Clock
from app.shared.contracts.files import FilesApi

UNFINISHED = (
    ItemStatus.DRAFT,
    ItemStatus.PENDING_REVIEW,
    ItemStatus.CHANGES_REQUESTED,
)
CLOSED_ACCOUNT = StatusReasonCode.ACCOUNT_CLOSED.value


class DeleteOwnerMaterials:
    """Drafts disappear, queued items are unpublished; published materials stay."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, files: FilesApi
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.files = files

    async def execute(self, user_id: UUID) -> int:
        """Return how many materials were removed or withdrawn."""
        now = self.clock.now()
        async with self.uow_factory() as uow:
            ids = await uow.moderation.owner_item_ids(user_id, UNFINISHED)
            for item in (await uow.items.get_many(ids)).values():
                if item.status is ItemStatus.DRAFT:
                    await uow.moderation.delete_draft(item.id)
                    for item_file in item.files:
                        uow.after_commit(
                            partial(self.files.delete_file, item_file.file_id)
                        )
                    continue
                item.status = ItemStatus.UNPUBLISHED
                item.status_reason = CLOSED_ACCOUNT
                item.status_note = None
                item.updated_at = now
                await uow.items.save(item)
                await uow.events.append(
                    item.id,
                    EventKind.UNPUBLISHED,
                    at=now,
                    actor_id=user_id,
                    data={"by": "owner", "reason": CLOSED_ACCOUNT},
                )
            await uow.commit()
        return len(ids)
