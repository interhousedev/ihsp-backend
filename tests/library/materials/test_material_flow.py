"""LIB-13, LIB-14: every arrow of the material state machine (doc § 3.5), pure rules."""

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
from app.modules.library.domain.material_flow import (
    ReviewAction,
    check_reason,
    check_reviewer,
    external_visibility,
    review_outcome,
    submit_outcome,
    uploader_role_of,
    visibility_for,
    withdraw_outcome,
)
from app.shared.actor import Role
from app.shared.ids import new_id

import pytest

OWNER = new_id()
OTHER = new_id()
ALL_STATUSES = list(ItemStatus)

# - - - Submit - - -


@pytest.mark.parametrize("status", [ItemStatus.DRAFT, ItemStatus.CHANGES_REQUESTED])
def test_student_submit_waits_for_review(status: ItemStatus) -> None:
    """LIB-13: a student's submitted material goes to the librarian queue."""
    outcome = submit_outcome(status, UploaderRole.STUDENT, teacher_review=False)

    assert outcome.status is ItemStatus.PENDING_REVIEW
    assert outcome.approval is None
    assert outcome.auto_approved is False


def test_librarian_submit_waits_for_another_librarian() -> None:
    """LIB-13: a librarian's upload is reviewed by somebody else."""
    outcome = submit_outcome(
        ItemStatus.DRAFT, UploaderRole.LIBRARIAN, teacher_review=False
    )

    assert outcome.status is ItemStatus.PENDING_REVIEW
    assert outcome.approval is None


def test_teacher_submit_publishes_at_once_by_role() -> None:
    """LIB-13: teachers are trusted; the item is published and marked auto-approved."""
    outcome = submit_outcome(
        ItemStatus.DRAFT, UploaderRole.TEACHER, teacher_review=False
    )

    assert outcome.status is ItemStatus.PUBLISHED
    assert outcome.approval is Approval.AUTO_TEACHER
    assert outcome.auto_approved is True


def test_teacher_review_setting_sends_teachers_to_the_queue() -> None:
    """LIB-13: LIBRARY__TEACHER_REVIEW=true puts teacher uploads in the queue too."""
    outcome = submit_outcome(
        ItemStatus.DRAFT, UploaderRole.TEACHER, teacher_review=True
    )

    assert outcome.status is ItemStatus.PENDING_REVIEW
    assert outcome.approval is None


@pytest.mark.parametrize("teacher_review", [False, True])
def test_admin_submit_publishes_at_once_whatever_the_setting(
    teacher_review: bool,
) -> None:
    """LIB-13: Administration publishes directly with approval `admin`."""
    outcome = submit_outcome(
        ItemStatus.DRAFT, UploaderRole.ADMIN, teacher_review=teacher_review
    )

    assert outcome.status is ItemStatus.PUBLISHED
    assert outcome.approval is Approval.ADMIN


@pytest.mark.parametrize(
    "status",
    [
        s
        for s in ALL_STATUSES
        if s not in {ItemStatus.DRAFT, ItemStatus.CHANGES_REQUESTED}
    ],
)
def test_submit_is_only_possible_from_draft_or_changes_requested(
    status: ItemStatus,
) -> None:
    """LIB-13: no other state has a submit arrow."""
    with pytest.raises(InvalidTransitionError):
        submit_outcome(status, UploaderRole.STUDENT, teacher_review=False)


# - - - Review decisions: the full matrix - - -

ALLOWED: dict[ReviewAction, dict[ItemStatus, ItemStatus]] = {
    ReviewAction.APPROVE: {ItemStatus.PENDING_REVIEW: ItemStatus.PUBLISHED},
    ReviewAction.REQUEST_CHANGES: {
        ItemStatus.PENDING_REVIEW: ItemStatus.CHANGES_REQUESTED
    },
    ReviewAction.REJECT: {ItemStatus.PENDING_REVIEW: ItemStatus.REJECTED},
    ReviewAction.HOLD: {ItemStatus.PUBLISHED: ItemStatus.HELD},
    ReviewAction.RESTORE: {
        ItemStatus.HELD: ItemStatus.PUBLISHED,
        ItemStatus.UNPUBLISHED: ItemStatus.PUBLISHED,
    },
    ReviewAction.UNPUBLISH: {
        ItemStatus.PUBLISHED: ItemStatus.UNPUBLISHED,
        ItemStatus.HELD: ItemStatus.UNPUBLISHED,
    },
}
MATRIX = [(a, s) for a in ReviewAction for s in ALL_STATUSES]


@pytest.mark.parametrize(("action", "status"), MATRIX)
def test_review_matrix_allows_exactly_the_arrows_of_the_doc(
    action: ReviewAction, status: ItemStatus
) -> None:
    """LIB-13, LIB-14: each action has the arrows of 3.5; all others are refused."""
    target = ALLOWED[action].get(status)

    if target is None:
        with pytest.raises(InvalidTransitionError) as caught:
            review_outcome(action, status)
        assert caught.value.params == {"status": status.value, "action": action.value}
    else:
        assert review_outcome(action, status) is target


# - - - Reasons - - -


@pytest.mark.parametrize(
    "action", [a for a in ReviewAction if a is not ReviewAction.APPROVE]
)
@pytest.mark.parametrize("reason", [None, "", "   "])
def test_every_decision_but_approve_needs_a_reason(
    action: ReviewAction, reason: str | None
) -> None:
    """LIB-13: reject, request changes, hold, restore and unpublish need a reason."""
    with pytest.raises(ReasonRequiredError):
        check_reason(action, reason)


def test_approve_needs_no_reason() -> None:
    """LIB-13: approving is the only decision without a reason."""
    assert check_reason(ReviewAction.APPROVE, None) is None


def test_the_reason_is_trimmed() -> None:
    """LIB-13: stray spaces around a reason are removed."""
    assert check_reason(ReviewAction.REJECT, "  duplicate ") == "duplicate"


# - - - Own-item rule - - -

SELF_REVIEW = [
    ReviewAction.APPROVE,
    ReviewAction.REQUEST_CHANGES,
    ReviewAction.REJECT,
    ReviewAction.RESTORE,
]


@pytest.mark.parametrize("action", SELF_REVIEW)
def test_a_librarian_cannot_review_their_own_upload(action: ReviewAction) -> None:
    """LIB-13: `library/own-item` for every decision that lets the item through."""
    with pytest.raises(OwnItemError):
        check_reviewer(
            action, owner_id=OWNER, reviewer_id=OWNER, reviewer_is_admin=False
        )


@pytest.mark.parametrize("action", ReviewAction)
def test_another_librarian_may_review(action: ReviewAction) -> None:
    """LIB-13: any other reviewer passes the own-item rule."""
    check_reviewer(action, owner_id=OWNER, reviewer_id=OTHER, reviewer_is_admin=False)


def test_administration_may_review_its_own_upload() -> None:
    """LIB-13: the rule has an exception for admins."""
    check_reviewer(
        ReviewAction.APPROVE, owner_id=OWNER, reviewer_id=OWNER, reviewer_is_admin=True
    )


@pytest.mark.parametrize("action", [ReviewAction.HOLD, ReviewAction.UNPUBLISH])
def test_a_librarian_may_hide_their_own_item(action: ReviewAction) -> None:
    """LIB-13: taking your own item down is not a way around review."""
    check_reviewer(action, owner_id=OWNER, reviewer_id=OWNER, reviewer_is_admin=False)


def test_an_item_without_owner_has_no_own_item_rule() -> None:
    """LIB-13: UniLibrary records have no owner."""
    no_owner: UUID | None = None

    check_reviewer(
        ReviewAction.RESTORE,
        owner_id=no_owner,
        reviewer_id=OTHER,
        reviewer_is_admin=False,
    )


# - - - Withdraw - - -


@pytest.mark.parametrize(
    "status",
    [
        ItemStatus.PENDING_REVIEW,
        ItemStatus.CHANGES_REQUESTED,
        ItemStatus.PUBLISHED,
        ItemStatus.HELD,
    ],
)
def test_owner_withdraw_unpublishes_a_live_item(status: ItemStatus) -> None:
    """LIB-13: owner withdraws -> unpublished."""
    assert withdraw_outcome(status) is ItemStatus.UNPUBLISHED


def test_withdrawing_a_draft_removes_it() -> None:
    """LIB-13: a draft never reached anyone, so it simply disappears."""
    assert withdraw_outcome(ItemStatus.DRAFT) is None


@pytest.mark.parametrize(
    "status", [ItemStatus.REJECTED, ItemStatus.UNPUBLISHED, ItemStatus.GONE]
)
def test_withdrawing_a_closed_item_changes_nothing(status: ItemStatus) -> None:
    """LIB-13: withdrawing twice is harmless."""
    assert withdraw_outcome(status) is status


# - - - Uploader role - - -


@pytest.mark.parametrize(
    ("roles", "expected"),
    [
        ({Role.STUDENT}, UploaderRole.STUDENT),
        ({Role.STUDENT, Role.LIBRARIAN}, UploaderRole.LIBRARIAN),
        ({Role.TEACHER}, UploaderRole.TEACHER),
        ({Role.TEACHER, Role.LIBRARIAN}, UploaderRole.TEACHER),
        ({Role.TEACHER, Role.ADMIN}, UploaderRole.ADMIN),
        ({Role.STUDENT, Role.LIBRARIAN, Role.ADMIN}, UploaderRole.ADMIN),
        ({Role.LMS_ADMIN}, UploaderRole.STUDENT),
    ],
)
def test_uploader_role_is_the_highest_of_admin_teacher_librarian_student(
    roles: set[Role], expected: UploaderRole
) -> None:
    """LIB-13: the role snapshot stored with a material."""
    assert uploader_role_of(frozenset(roles)) is expected


# - - - Visibility chosen at upload - - -


@pytest.mark.parametrize("licence", list(MaterialLicence))
@pytest.mark.parametrize("is_teacher", [False, True])
def test_only_a_teacher_with_a_creative_commons_licence_goes_public(
    licence: MaterialLicence, is_teacher: bool
) -> None:
    """LIB-13: everything else stays inside the lyceum."""
    expected = (
        Visibility.PUBLIC
        if is_teacher and licence is not MaterialLicence.ALL_RIGHTS_RESERVED
        else Visibility.LYCEUM
    )

    assert visibility_for(licence, is_teacher=is_teacher) is expected


# - - - UniLibrary records: hide and show - - -


def test_unpublishing_a_record_hides_it_and_keeps_its_status() -> None:
    """LIB-12: a librarian hides a UniLibrary record; the sync cannot unhide it."""
    shown = external_visibility(
        ReviewAction.UNPUBLISH, ItemStatus.PUBLISHED, Visibility.LYCEUM
    )

    assert shown is Visibility.HIDDEN


def test_hiding_a_hidden_record_again_is_refused() -> None:
    """LIB-12: nothing to hide."""
    with pytest.raises(InvalidTransitionError):
        external_visibility(
            ReviewAction.UNPUBLISH, ItemStatus.PUBLISHED, Visibility.HIDDEN
        )


def test_restoring_a_hidden_record_shows_it_in_the_lyceum() -> None:
    """LIB-12: restore reverses the hide."""
    shown = external_visibility(
        ReviewAction.RESTORE, ItemStatus.PUBLISHED, Visibility.HIDDEN
    )

    assert shown is Visibility.LYCEUM


@pytest.mark.parametrize(
    ("action", "status", "visibility"),
    [
        (ReviewAction.HOLD, ItemStatus.PUBLISHED, Visibility.LYCEUM),
        (ReviewAction.RESTORE, ItemStatus.HELD, Visibility.LYCEUM),
        (ReviewAction.RESTORE, ItemStatus.HELD, Visibility.HIDDEN),
        (ReviewAction.APPROVE, ItemStatus.PENDING_REVIEW, Visibility.LYCEUM),
    ],
)
def test_other_decisions_on_a_record_follow_the_normal_status_flow(
    action: ReviewAction, status: ItemStatus, visibility: Visibility
) -> None:
    """LIB-12: only hide and show are special; `None` means use the status flow."""
    assert external_visibility(action, status, visibility) is None


@pytest.mark.parametrize(
    "status", [ItemStatus.DRAFT, ItemStatus.GONE, ItemStatus.UNPUBLISHED]
)
def test_only_a_live_record_can_be_hidden(status: ItemStatus) -> None:
    """LIB-12: gone and closed records are already out of sight."""
    with pytest.raises(InvalidTransitionError):
        external_visibility(ReviewAction.UNPUBLISH, status, Visibility.LYCEUM)
