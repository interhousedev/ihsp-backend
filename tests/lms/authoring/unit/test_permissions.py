"""LMS-5, LMS-21: staff permissions and role presets."""

from collections.abc import Callable

from app.modules.lms.domain.authoring.entities import StaffMember
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    StaffInvalidError,
)
from app.modules.lms.domain.authoring.permissions import (
    EDIT,
    MANAGE_STAFF,
    PUBLISH,
    REVIEW,
    VIEW_DRAFTS,
    CourseAccess,
    normalize_permissions,
    normalize_role,
    preset_permissions,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id

import pytest


def _member(*permissions: str) -> StaffMember:
    return StaffMember(
        course_id=new_id(),
        user_id=new_id(),
        role="Teacher",
        permissions=list(permissions),
        show_on_page=True,
        position=0,
        added_by=new_id(),
    )


def test_role_presets_fill_typical_permissions() -> None:
    """LMS-5: Owner has all, Teacher edit+publish+review+view_drafts, others one."""
    assert preset_permissions("Owner") == [
        EDIT,
        PUBLISH,
        REVIEW,
        MANAGE_STAFF,
        VIEW_DRAFTS,
    ]
    assert preset_permissions("teacher") == [EDIT, PUBLISH, REVIEW, VIEW_DRAFTS]
    assert preset_permissions("Reviewer") == [REVIEW]
    assert preset_permissions("Support") == [REVIEW]
    assert preset_permissions("Tester") == [VIEW_DRAFTS]
    assert preset_permissions("Assistant teacher") is None


def test_lms_admin_can_do_everything_without_a_staff_row(
    make_actor: Callable[..., Actor],
) -> None:
    """LMS-21: the LMS admin manages all courses."""
    access = CourseAccess(actor=make_actor(Role.LMS_ADMIN), staff=None)

    assert access.is_staff
    assert all(
        access.can(p) for p in (EDIT, PUBLISH, REVIEW, MANAGE_STAFF, VIEW_DRAFTS)
    )


def test_staff_member_holds_only_granted_permissions(
    make_actor: Callable[..., Actor],
) -> None:
    """LMS-5: a Tester previews but cannot edit."""
    access = CourseAccess(actor=make_actor(Role.TEACHER), staff=_member(VIEW_DRAFTS))

    assert access.can(VIEW_DRAFTS)
    assert not access.can(EDIT)
    with pytest.raises(CoursePermissionError):
        access.require(EDIT)
    access.require(EDIT, VIEW_DRAFTS)


def test_outsider_is_not_staff(make_actor: Callable[..., Actor]) -> None:
    """A teacher without a staff row has no access to the course."""
    access = CourseAccess(actor=make_actor(Role.TEACHER), staff=None)

    assert not access.is_staff
    assert access.permissions == []
    with pytest.raises(CoursePermissionError):
        access.require_staff()


def test_unknown_permission_is_rejected() -> None:
    """LMS-5: only the five permissions exist."""
    with pytest.raises(StaffInvalidError):
        normalize_permissions([EDIT, "delete_everything"])


def test_permissions_are_deduplicated_and_ordered() -> None:
    """The stored order is canonical."""
    assert normalize_permissions([VIEW_DRAFTS, EDIT, EDIT]) == [EDIT, VIEW_DRAFTS]


@pytest.mark.parametrize("role", ["", "   ", "x" * 41])
def test_role_label_must_have_1_to_40_characters(role: str) -> None:
    """LMS-5: the role is a short free label."""
    with pytest.raises(StaffInvalidError):
        normalize_role(role)
