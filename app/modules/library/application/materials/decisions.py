"""A librarian's decision about an item, applied: status, history, audit, notice.

Shared by `ReviewItem` (a librarian clicks), `ResolveReport` (a report is decided)
and `ReportItem` (the auto-hold), so all three change an item the same way.
"""

from dataclasses import dataclass
from uuid import UUID

from app.modules.library.application.materials.audit_types import REQUEST_CHANGES
from app.modules.library.application.materials.notices import owner_notice
from app.modules.library.application.materials.publishing import (
    SUPERSEDED,
    supersede_previous,
)
from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import (
    Approval,
    EventKind,
    ItemKind,
    ItemStatus,
    ReportStatus,
    Visibility,
)
from app.modules.library.domain.errors import InvalidTransitionError
from app.modules.library.domain.material_flow import (
    ReviewAction,
    external_visibility,
    review_outcome,
)
from app.modules.library.ports.unit_of_work import LibraryUnitOfWork
from app.shared.clock import Clock
from app.shared.library_audit import LibraryAuditType
from app.shared.notifications import AuditDraft

_EVENT = {
    ReviewAction.APPROVE: EventKind.APPROVED,
    ReviewAction.REQUEST_CHANGES: EventKind.CHANGES_REQUESTED,
    ReviewAction.REJECT: EventKind.REJECTED,
    ReviewAction.HOLD: EventKind.HELD,
    ReviewAction.RESTORE: EventKind.RESTORED,
    ReviewAction.UNPUBLISH: EventKind.UNPUBLISHED,
}
_AUDIT = {
    ReviewAction.APPROVE: LibraryAuditType.APPROVE.value,
    ReviewAction.REQUEST_CHANGES: REQUEST_CHANGES,
    ReviewAction.REJECT: LibraryAuditType.REJECT.value,
    ReviewAction.HOLD: LibraryAuditType.HOLD.value,
    ReviewAction.RESTORE: LibraryAuditType.RESTORE.value,
    ReviewAction.UNPUBLISH: LibraryAuditType.UNPUBLISH.value,
}
_REVIEWED = frozenset(
    {ReviewAction.APPROVE, ReviewAction.REQUEST_CHANGES, ReviewAction.REJECT}
)
# Decisions that leave a reason (and a note) on the item for its owner to read.
_WITH_REASON = frozenset(
    {
        ReviewAction.REQUEST_CHANGES,
        ReviewAction.REJECT,
        ReviewAction.HOLD,
        ReviewAction.UNPUBLISH,
    }
)


@dataclass(frozen=True, slots=True)
class Decision:
    """What was decided, why, by whom (`actor_id` None is the system)."""

    action: ReviewAction
    reason: str | None = None
    note: str | None = None
    actor_id: UUID | None = None
    actor_is_admin: bool = False


@dataclass(frozen=True, slots=True)
class _Change:
    """The new state of the item and the history entry for it."""

    status: ItemStatus
    visibility: Visibility
    event: EventKind
    hides_only: bool = False


def decide(item: Item, action: ReviewAction) -> _Change:
    """The state after `action`; UniLibrary records are hidden, not unpublished."""
    if item.kind is ItemKind.EXTERNAL:
        shown = external_visibility(action, item.status, item.visibility)
        if shown is not None:
            event = (
                EventKind.HIDDEN if shown is Visibility.HIDDEN else EventKind.RESTORED
            )
            return _Change(item.status, shown, event, hides_only=True)
    if action is ReviewAction.RESTORE and item.status_reason == SUPERSEDED:
        raise InvalidTransitionError(
            params={"status": item.status.value, "action": action.value}
        )
    status = review_outcome(action, item.status)
    return _Change(status, item.visibility, _EVENT[action])


class Decisions:
    """Applies decisions inside an open unit of work (the caller commits)."""

    def __init__(self, *, clock: Clock) -> None:
        """Store the clock."""
        self.clock = clock

    async def apply(
        self, uow: LibraryUnitOfWork, item: Item, decision: Decision
    ) -> int:
        """Change the item and record it; return the sequence number of the event."""
        change = decide(item, decision.action)
        now = self.clock.now()
        self._stamp(item, change, decision)
        await uow.items.save(item)
        closed = await self._close_reports(uow, item, decision)
        if decision.action is ReviewAction.APPROVE:
            await supersede_previous(uow, item, at=now, actor_id=decision.actor_id)
        event = await uow.events.append(
            item.id,
            change.event,
            at=now,
            actor_id=decision.actor_id,
            data=_event_data(decision),
        )
        uow.audit(self._audit(item, decision, closed))
        notice = owner_notice(
            decision.action,
            item,
            reason=decision.reason,
            note=decision.note,
            seq=event.seq,
        )
        if notice is not None and notice.user_id != decision.actor_id:
            uow.notify(notice)
        return event.seq

    def _stamp(self, item: Item, change: _Change, decision: Decision) -> None:
        now = self.clock.now()
        action = decision.action
        item.status = change.status
        item.visibility = change.visibility
        item.updated_at = now
        if change.hides_only:
            return
        with_reason = action in _WITH_REASON
        item.status_reason = decision.reason if with_reason else None
        item.status_note = decision.note if with_reason else None
        if action in _REVIEWED:
            item.reviewed_by = decision.actor_id
            item.reviewed_at = now
            self._stamp_material(item, decision)
        if action is ReviewAction.APPROVE:
            item.published_at = now

    @staticmethod
    def _stamp_material(item: Item, decision: Decision) -> None:
        if item.material is None:
            return
        if decision.action is ReviewAction.APPROVE:
            item.material.approval = (
                Approval.ADMIN if decision.actor_is_admin else Approval.LIBRARIAN
            )
        else:
            item.material.review_message = decision.note or decision.reason

    async def _close_reports(
        self, uow: LibraryUnitOfWork, item: Item, decision: Decision
    ) -> int:
        """Restoring dismisses the open reports, unpublishing upholds them."""
        if decision.action not in {ReviewAction.RESTORE, ReviewAction.UNPUBLISH}:
            return 0
        status = (
            ReportStatus.DISMISSED
            if decision.action is ReviewAction.RESTORE
            else ReportStatus.UPHELD
        )
        closed = await uow.moderation.close_reports(
            item.id,
            status,
            handled_by=decision.actor_id,
            at=self.clock.now(),
            action=decision.action.value,
        )
        item.open_reports = 0
        await uow.items.save(item)
        return closed

    @staticmethod
    def _audit(item: Item, decision: Decision, closed: int) -> AuditDraft:
        metadata: dict[str, object] = {"item_id": str(item.id), **_event_data(decision)}
        if closed:
            metadata["reports_closed"] = closed
        return AuditDraft(
            type=_AUDIT[decision.action],
            user_id=item.owner_id,
            actor_id=decision.actor_id,
            metadata=metadata,
        )


def _event_data(decision: Decision) -> dict[str, object]:
    data: dict[str, object] = {"action": decision.action.value}
    if decision.actor_id is None:
        data["auto"] = True
    if decision.reason:
        data["reason"] = decision.reason
    if decision.note:
        data["note"] = decision.note
    return data
