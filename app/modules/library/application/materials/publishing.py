"""What happens around a publication: a new version replaces the one it supersedes."""

from datetime import datetime
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind, ItemStatus, StatusReasonCode
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork

SUPERSEDED = StatusReasonCode.SUPERSEDED.value


async def supersede_previous(
    uow: LibraryUnitOfWork, item: Item, *, at: datetime, actor_id: UUID | None
) -> None:
    """Unpublish the version `item` replaces, now that `item` is published.

    The old version stays published until this moment, so readers never see a gap.
    """
    if item.supersedes_id is None:
        return
    old = await uow.items.get(item.supersedes_id, lock=True)
    if old is None or old.status is not ItemStatus.PUBLISHED:
        return
    old.status = ItemStatus.UNPUBLISHED
    old.status_reason = SUPERSEDED
    old.status_note = None
    old.updated_at = at
    await uow.items.save(old)
    await uow.events.append(
        old.id,
        EventKind.UNPUBLISHED,
        at=at,
        actor_id=actor_id,
        data={"superseded_by": str(item.id)},
    )
