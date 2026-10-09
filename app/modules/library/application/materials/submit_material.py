"""Submit a draft material for review, or publish it at once for teachers (LIB-13)."""

from uuid import UUID

from app.modules.library.application.detail import DetailBuilder, ItemDetailView
from app.modules.library.application.materials.loading import load_owned
from app.modules.library.application.materials.publishing import supersede_previous
from app.modules.library.application.materials.upload_guard import UploadGuard
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import EventKind
from app.modules.library.domain.errors import AttestationRequiredError, NoFilesError
from app.modules.library.domain.material_flow import SubmitOutcome, submit_outcome
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor
from app.shared.clock import Clock
from app.shared.library_audit import LibraryAuditType
from app.shared.notifications import AuditDraft


class SubmitMaterial:
    """Draft or sent-back material -> review queue, or published by role."""

    def __init__(
        self,
        *,
        uow_factory: UowFactory,
        clock: Clock,
        guard: UploadGuard,
        detail: DetailBuilder,
        teacher_review: bool,
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.guard = guard
        self.detail = detail
        self.teacher_review = teacher_review

    async def execute(
        self, actor: Actor, item_id: UUID, *, locale: str
    ) -> ItemDetailView:
        """Check the ban and the limits, then move the material on."""
        async with self.uow_factory() as uow:
            item = await load_owned(uow, item_id, actor, lock=True)
            assert item.material is not None
            outcome = submit_outcome(
                item.status,
                item.material.uploader_role,
                teacher_review=self.teacher_review,
            )
            if item.material.attested_at is None:
                raise AttestationRequiredError()
            if not item.files:
                raise NoFilesError()
            await self.guard.ensure_not_banned(uow, actor.user_id)
            await self.guard.ensure_within_limits(
                uow, actor.user_id, item.material.uploader_role, exclude=item.id
            )
            await self._apply(uow, item, outcome, actor)
            view = await self.detail.build(uow, item, viewer=actor, locale=locale)
            await uow.commit()
        return view

    async def _apply(
        self, uow: LibraryUnitOfWork, item: Item, outcome: SubmitOutcome, actor: Actor
    ) -> None:
        assert item.material is not None
        now = self.clock.now()
        item.status = outcome.status
        item.status_reason = None
        item.status_note = None
        item.updated_at = now
        item.material.submitted_at = now
        item.material.approval = outcome.approval
        await uow.events.append(
            item.id, EventKind.SUBMITTED, at=now, actor_id=actor.user_id
        )
        if outcome.auto_approved:
            item.published_at = now
            await uow.items.save(item)
            await self._auto_approve(uow, item, outcome, actor)
        else:
            await uow.items.save(item)

    async def _auto_approve(
        self, uow: LibraryUnitOfWork, item: Item, outcome: SubmitOutcome, actor: Actor
    ) -> None:
        approval = outcome.approval.value if outcome.approval else None
        await uow.events.append(
            item.id,
            EventKind.APPROVED,
            at=self.clock.now(),
            actor_id=actor.user_id,
            data={"auto": True, "approval": approval},
        )
        uow.audit(
            AuditDraft(
                type=LibraryAuditType.AUTO_APPROVE.value,
                user_id=item.owner_id,
                actor_id=actor.user_id,
                metadata={"item_id": str(item.id), "approval": approval},
            )
        )
        await supersede_previous(uow, item, at=self.clock.now(), actor_id=actor.user_id)
