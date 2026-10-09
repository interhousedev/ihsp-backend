"""Notifications of the materials area (payloads: `notify/.../describe.py`)."""

from collections.abc import Iterable
from uuid import UUID

from app.modules.library.domain.entities import Item
from app.modules.library.domain.enums import ReportReason
from app.modules.library.domain.material_flow import ReviewAction
from app.shared.notifications import NotificationDraft, NotificationType


def _draft(
    user_id: UUID,
    kind: NotificationType,
    item_id: UUID,
    seq: int,
    payload: dict[str, object],
) -> NotificationDraft:
    return NotificationDraft(
        user_id=user_id,
        type=kind,
        payload=payload,
        dedupe_key=f"{kind.value}:{item_id}:{seq}",
    )


def owner_notice(
    action: ReviewAction,
    item: Item,
    *,
    reason: str | None,
    note: str | None,
    seq: int,
) -> NotificationDraft | None:
    """What the owner is told about a decision; hold and restore stay silent.

    The librarian who decided is never named: the payload has no reviewer.
    """
    if item.owner_id is None:
        return None
    base: dict[str, object] = {"item_id": str(item.id), "title": item.title}
    match action:
        case ReviewAction.APPROVE:
            kind, payload = NotificationType.LIBRARY_ITEM_APPROVED, base
        case ReviewAction.REQUEST_CHANGES:
            kind = NotificationType.LIBRARY_ITEM_CHANGES_REQUESTED
            payload = {**base, "message": note or reason}
        case ReviewAction.REJECT:
            kind = NotificationType.LIBRARY_ITEM_REJECTED
            payload = {**base, "reason": reason, "message": note}
        case ReviewAction.UNPUBLISH:
            kind = NotificationType.LIBRARY_ITEM_UNPUBLISHED
            payload = {**base, "reason": reason, "note": note}
        case _:
            return None
    return _draft(item.owner_id, kind, item.id, seq, payload)


def report_filed_notices(
    item: Item, reason: ReportReason, recipients: Iterable[UUID], seq: int
) -> list[NotificationDraft]:
    """Tell librarians an item was held after reports; the reporter is not named."""
    payload: dict[str, object] = {
        "item_id": str(item.id),
        "title": item.title,
        "reason": reason.value,
    }
    kind = NotificationType.LIBRARY_REPORT_FILED
    # Keys are unique across users, so each recipient gets their own.
    return [
        NotificationDraft(
            user_id=user_id,
            type=kind,
            payload=payload,
            dedupe_key=f"{kind.value}:{user_id}:{item.id}:{seq}",
        )
        for user_id in recipients
    ]
