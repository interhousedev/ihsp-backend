"""Teachers may own notebooks; the subject and lesson routes stay for students."""

from uuid import uuid4

import pytest

from app.interfaces.http.v1.notebooks import deps
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError


def _actor(*roles: Role) -> Actor:
    return Actor(user_id=uuid4(), roles=frozenset(roles))


@pytest.mark.parametrize("role", [Role.STUDENT, Role.TEACHER])
async def test_owner_dependency_admits_students_and_teachers(role: Role) -> None:
    actor = _actor(role)
    assert await deps._owner(actor) is actor


async def test_owner_dependency_rejects_other_roles() -> None:
    with pytest.raises(ForbiddenError):
        await deps._owner(_actor(Role.LIBRARIAN))


async def test_student_dependency_still_rejects_teachers() -> None:
    with pytest.raises(ForbiddenError):
        await deps._student(_actor(Role.TEACHER))
