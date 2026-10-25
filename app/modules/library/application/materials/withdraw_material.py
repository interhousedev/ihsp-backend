"""The owner takes a material back (LIB-13)."""

from uuid import UUID

from app.modules.library.application.materials.drafts import MaterialDrafts
from app.modules.library.application.materials.loading import load_owned
from app.modules.library.domain.enums import EventKind, ItemStatus, StatusReasonCode
from app.modules.library.domain.material_flow import withdraw_outcome
from app.modules.library.ports.unit_of_work import UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock

WITHDRAWN = StatusReasonCode.WITHDRAWN_BY_OWNER.value


class WithdrawMaterial:
    """A draft disappears; anything else becomes `unpublished` (files go in 90 days)."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, drafts: MaterialDrafts
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.drafts = drafts

    async def execute(self, actor: Actor, item_id: UUID) -> None:
        """Withdraw the material; withdrawing a closed one again is a no-op."""
        async with self.uow_factory() as uow:
            item = await load_owned(uow, item_id, actor, lock=True)
            outcome = withdraw_outcome(item.status)
            if outcome is None:
                await uow.moderation.delete_draft(item.id)
                self.drafts.delete_after_commit(uow, [f.file_id for f in item.files])
            elif outcome is ItemStatus.UNPUBLISHED and item.status is not outcome:
                now = self.clock.now()
                item.status = outcome
                item.status_reason = WITHDRAWN
                item.status_note = None
                item.updated_at = now
                await uow.items.save(item)
                await uow.events.append(
                    item.id,
                    EventKind.UNPUBLISHED,
                    at=now,
                    actor_id=actor.user_id,
                    data={"by": "owner"},
                )
            await uow.commit()
