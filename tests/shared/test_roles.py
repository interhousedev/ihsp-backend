"""ADM-5, LIB-1: the `librarian` role next to the others."""

from uuid import UUID

from app.shared.actor import SYSTEM_ACTOR, Actor, Role
from app.shared.base_error import ForbiddenError

import pytest

USER = UUID(int=7)


def test_the_librarian_role_has_its_stored_name() -> None:
    """LIB-1: `users.roles` keeps the lower-case name."""
    assert Role.LIBRARIAN == "librarian"
    assert Role("librarian") is Role.LIBRARIAN


def test_a_student_can_hold_the_librarian_role_too() -> None:
    """LIB-1: roles are a set, `student` and `librarian` together."""
    actor = Actor(user_id=USER, roles=frozenset({Role.STUDENT, Role.LIBRARIAN}))

    actor.require(Role.LIBRARIAN, Role.ADMIN)

    assert actor.has(Role.STUDENT)
    assert actor.has(Role.LIBRARIAN)


def test_a_librarian_only_actor_is_no_student_no_teacher_no_admin() -> None:
    """LIB-1: the role grants nothing beyond the library."""
    actor = Actor(user_id=USER, roles=frozenset({Role.LIBRARIAN}))

    for other in (Role.STUDENT, Role.TEACHER, Role.ADMIN, Role.LMS_ADMIN):
        assert not actor.has(other)
        with pytest.raises(ForbiddenError):
            actor.require(other)


def test_the_system_actor_holds_every_role() -> None:
    """GEN-6: jobs act with all roles, the librarian one included."""
    assert SYSTEM_ACTOR.has(Role.LIBRARIAN)
