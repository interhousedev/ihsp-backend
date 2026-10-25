"""Status changes of a library item (doc § 3.5): pure rules, no I/O.

```
draft ─submit─> pending_review ─approve─> published
  │                  ├─request changes─> changes_requested ─resubmit─> pending_review
  │                  └─reject (reason)─> rejected
  └─ teacher (default) ─────────────────> published   (auto-approved by role)
published ─reports─> held ─restore─> published
                          └─unpublish─> unpublished
published ─takedown, owner withdraws─> unpublished
```
"""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from app.modules.library.domain.enums import (
    Approval,
    ItemStatus,
    MaterialLicence,
    UploaderRole,
    Visibility,
)
from app.modules.library.domain.errors import (
    InvalidTransitionError,
    OwnItemError,
    ReasonRequiredError,
)
from app.shared.actor import Role


class ReviewAction(StrEnum):
    """A librarian's decision about an item."""

    APPROVE = "approve"
    REQUEST_CHANGES = "request_changes"
    REJECT = "reject"
    HOLD = "hold"
    RESTORE = "restore"
    UNPUBLISH = "unpublish"


class ResolveAction(StrEnum):
    """What a librarian decides about the open reports of an item."""

    DISMISS = "dismiss"
    HOLD = "hold"
    UNPUBLISH = "unpublish"
    UNPUBLISH_AND_WARN = "unpublish_and_warn"


@dataclass(frozen=True, slots=True)
class SubmitOutcome:
    """Where a submitted material lands, and how it got there."""

    status: ItemStatus
    approval: Approval | None = None

    @property
    def auto_approved(self) -> bool:
        """True when the role published the item without a librarian."""
        return self.approval in {Approval.AUTO_TEACHER, Approval.ADMIN}


SUBMITTABLE = frozenset({ItemStatus.DRAFT, ItemStatus.CHANGES_REQUESTED})
# Closed items stay as they are when the owner withdraws again.
CLOSED = frozenset({ItemStatus.REJECTED, ItemStatus.UNPUBLISHED, ItemStatus.GONE})
# Decisions that let an item through, so they cannot be made on one's own upload.
SELF_REVIEW_BLOCKED = frozenset(
    {
        ReviewAction.APPROVE,
        ReviewAction.REQUEST_CHANGES,
        ReviewAction.REJECT,
        ReviewAction.RESTORE,
    }
)
_REVIEW: dict[ReviewAction, tuple[frozenset[ItemStatus], ItemStatus]] = {
    ReviewAction.APPROVE: (
        frozenset({ItemStatus.PENDING_REVIEW}),
        ItemStatus.PUBLISHED,
    ),
    ReviewAction.REQUEST_CHANGES: (
        frozenset({ItemStatus.PENDING_REVIEW}),
        ItemStatus.CHANGES_REQUESTED,
    ),
    ReviewAction.REJECT: (frozenset({ItemStatus.PENDING_REVIEW}), ItemStatus.REJECTED),
    ReviewAction.HOLD: (frozenset({ItemStatus.PUBLISHED}), ItemStatus.HELD),
    ReviewAction.RESTORE: (
        frozenset({ItemStatus.HELD, ItemStatus.UNPUBLISHED}),
        ItemStatus.PUBLISHED,
    ),
    ReviewAction.UNPUBLISH: (
        frozenset({ItemStatus.PUBLISHED, ItemStatus.HELD}),
        ItemStatus.UNPUBLISHED,
    ),
}


def uploader_role_of(roles: frozenset[Role]) -> UploaderRole:
    """The highest role of the uploader: admin, teacher, librarian, then student."""
    if Role.ADMIN in roles:
        return UploaderRole.ADMIN
    if Role.TEACHER in roles:
        return UploaderRole.TEACHER
    if Role.LIBRARIAN in roles:
        return UploaderRole.LIBRARIAN
    return UploaderRole.STUDENT


def submit_outcome(
    status: ItemStatus, role: UploaderRole, *, teacher_review: bool
) -> SubmitOutcome:
    """The status after submit: the queue, or published at once for teachers/admins."""
    if status not in SUBMITTABLE:
        raise InvalidTransitionError(
            params={"status": status.value, "action": "submit"}
        )
    if role is UploaderRole.ADMIN:
        return SubmitOutcome(ItemStatus.PUBLISHED, Approval.ADMIN)
    if role is UploaderRole.TEACHER and not teacher_review:
        return SubmitOutcome(ItemStatus.PUBLISHED, Approval.AUTO_TEACHER)
    return SubmitOutcome(ItemStatus.PENDING_REVIEW)


def review_outcome(action: ReviewAction, status: ItemStatus) -> ItemStatus:
    """The status after a librarian's decision; an illegal arrow is refused."""
    sources, target = _REVIEW[action]
    if status not in sources:
        raise InvalidTransitionError(
            params={"status": status.value, "action": action.value}
        )
    return target


def check_reason(action: ReviewAction, reason: str | None) -> str | None:
    """The trimmed reason; every decision but approve needs one."""
    text = (reason or "").strip()
    if action is not ReviewAction.APPROVE and not text:
        raise ReasonRequiredError(params={"field": "reason"})
    return text or None


def check_reviewer(
    action: ReviewAction,
    *,
    owner_id: UUID | None,
    reviewer_id: UUID,
    reviewer_is_admin: bool,
) -> None:
    """Refuse `library/own-item`: nobody lets their own upload through (admin may)."""
    if (
        action in SELF_REVIEW_BLOCKED
        and owner_id == reviewer_id
        and not reviewer_is_admin
    ):
        raise OwnItemError(params={"action": action.value})


def withdraw_outcome(status: ItemStatus) -> ItemStatus | None:
    """What the owner's withdraw does: None removes a draft, closed items stay."""
    if status is ItemStatus.DRAFT:
        return None
    if status in CLOSED:
        return status
    return ItemStatus.UNPUBLISHED


def visibility_for(licence: MaterialLicence, *, is_teacher: bool) -> Visibility:
    """`public` only for a teacher who chose a Creative Commons licence (doc § 3.5)."""
    if is_teacher and licence is not MaterialLicence.ALL_RIGHTS_RESERVED:
        return Visibility.PUBLIC
    return Visibility.LYCEUM


LIVE = frozenset({ItemStatus.PUBLISHED, ItemStatus.HELD})


def external_visibility(
    action: ReviewAction, status: ItemStatus, visibility: Visibility
) -> Visibility | None:
    """The new visibility when a UniLibrary record is hidden or shown again.

    Records have no review states of their own: unpublishing hides the record and
    restoring a hidden one shows it. `None` means the normal status flow applies.
    """
    if action is ReviewAction.UNPUBLISH:
        if status not in LIVE or visibility is Visibility.HIDDEN:
            raise InvalidTransitionError(
                params={"status": status.value, "action": action.value}
            )
        return Visibility.HIDDEN
    if (
        action is ReviewAction.RESTORE
        and status is ItemStatus.PUBLISHED
        and visibility is Visibility.HIDDEN
    ):
        return Visibility.LYCEUM
    return None
