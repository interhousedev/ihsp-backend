"""A librarian decides about the reports of an item (LIB-14)."""

from uuid import UUID

from app.modules.library.application.materials.audit_types import REPORT_DISMISS
from app.modules.library.application.materials.decisions import Decision, Decisions
from app.modules.library.application.materials.report_item import HELD_BY_REPORTS
from app.modules.library.domain.access import is_librarian
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    ItemStatus,
    ReportReason,
    ReportStatus,
    SanctionKind,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    ItemNotFoundError,
    ReportNotFoundError,
)
from app.modules.library.domain.material_flow import ResolveAction, ReviewAction
from app.modules.library.domain.moderation_entities import Sanction
from app.modules.library.domain.moderation_rules import top_reason
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork, UowFactory
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.library_audit import LibraryAuditType
from app.shared.notifications import AuditDraft


class ResolveReport:
    """Applies to every open report of the item the given report is about."""

    def __init__(
        self, *, uow_factory: UowFactory, clock: Clock, decisions: Decisions
    ) -> None:
        """Initialize the use case."""
        self.uow_factory = uow_factory
        self.clock = clock
        self.decisions = decisions

    async def execute(
        self, actor: Actor, report_id: UUID, action: ResolveAction
    ) -> None:
        """Decide; resolving a report that is already closed does nothing."""
        if not is_librarian(actor):
            raise ForbiddenError(params={"roles": ["librarian", "admin"]})
        async with self.uow_factory() as uow:
            report = await uow.moderation.get_report(report_id)
            if report is None:
                raise ReportNotFoundError()
            if report.status is not ReportStatus.OPEN:
                return
            item = await uow.items.get(report.item_id, lock=True)
            if item is None:
                raise ItemNotFoundError()
            await self._decide(uow, item, actor, action)
            await uow.commit()

    async def _decide(
        self, uow: LibraryUnitOfWork, item: Item, actor: Actor, action: ResolveAction
    ) -> None:
        decision = Decision(
            ReviewAction.HOLD,
            actor_id=actor.user_id,
            actor_is_admin=Role.ADMIN in actor.roles,
        )
        if action is ResolveAction.DISMISS:
            await self._dismiss(uow, item, decision)
        elif action is ResolveAction.HOLD:
            await self._hold(uow, item, decision)
        else:
            await self._take_down(
                uow, item, decision, warn=action is ResolveAction.UNPUBLISH_AND_WARN
            )

    async def _dismiss(
        self, uow: LibraryUnitOfWork, item: Item, decision: Decision
    ) -> None:
        if item.status is ItemStatus.HELD:
            await self.decisions.apply(
                uow,
                item,
                Decision(
                    ReviewAction.RESTORE,
                    reason="dismissed",
                    actor_id=decision.actor_id,
                    actor_is_admin=decision.actor_is_admin,
                ),
            )
            return
        closed = await uow.moderation.close_reports(
            item.id,
            ReportStatus.DISMISSED,
            handled_by=decision.actor_id,
            at=self.clock.now(),
            action=ResolveAction.DISMISS.value,
        )
        item.open_reports = 0
        await uow.items.save(item)
        uow.audit(
            AuditDraft(
                type=REPORT_DISMISS,
                user_id=item.owner_id,
                actor_id=decision.actor_id,
                metadata={"item_id": str(item.id), "reports_closed": closed},
            )
        )

    async def _hold(
        self, uow: LibraryUnitOfWork, item: Item, decision: Decision
    ) -> None:
        if item.status is ItemStatus.HELD:
            return
        await self.decisions.apply(
            uow,
            item,
            Decision(
                ReviewAction.HOLD,
                reason=HELD_BY_REPORTS,
                actor_id=decision.actor_id,
                actor_is_admin=decision.actor_is_admin,
            ),
        )

    async def _take_down(
        self, uow: LibraryUnitOfWork, item: Item, decision: Decision, *, warn: bool
    ) -> None:
        if item.status not in {ItemStatus.PUBLISHED, ItemStatus.HELD}:
            raise InvalidTransitionError(
                params={"status": item.status.value, "action": "unpublish"}
            )
        reasons = [r.reason for r in await uow.moderation.open_reports(item.id)]
        reason = top_reason(reasons) or ReportReason.OTHER
        await self.decisions.apply(
            uow,
            item,
            Decision(
                ReviewAction.UNPUBLISH,
                reason=reason.value,
                actor_id=decision.actor_id,
                actor_is_admin=decision.actor_is_admin,
            ),
        )
        if warn and item.owner_id is not None and decision.actor_id is not None:
            await self._warn(uow, item, decision.actor_id, reason)

    async def _warn(
        self, uow: LibraryUnitOfWork, item: Item, actor_id: UUID, reason: ReportReason
    ) -> None:
        assert item.owner_id is not None
        await uow.moderation.add_sanction(
            Sanction(
                id=new_id(),
                user_id=item.owner_id,
                kind=SanctionKind.WARNING,
                reason=f"upheld report: {reason.value}",
                set_by=actor_id,
                created_at=self.clock.now(),
                item_id=item.id,
            )
        )
        uow.audit(
            AuditDraft(
                type=LibraryAuditType.SANCTION.value,
                user_id=item.owner_id,
                actor_id=actor_id,
                metadata={
                    "item_id": str(item.id),
                    "kind": SanctionKind.WARNING.value,
                    "reason": reason.value,
                },
            )
        )
