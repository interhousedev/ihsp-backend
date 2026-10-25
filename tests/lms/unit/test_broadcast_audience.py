"""The audience of a course broadcast: the enrolled students, for course admins only."""

from typing import Any
from uuid import UUID

from app.modules.lms.application.learning.list_broadcast_audience import (
    ListBroadcastAudience,
)
from app.modules.lms.domain.learning.entities import (
    Enrollment,
    LearningCourse,
    StaffMember,
)
from app.modules.lms.domain.learning.errors import CoursePermissionError
from app.shared.actor import Actor, Role
from app.shared.ids import new_id

import pytest

COURSE = LearningCourse(
    id=new_id(),
    slug="algebra-9",
    title="Algebra",
    description="",
    cover_file_id=None,
    visibility="public",
    invite_code=None,
    status="active",
    live_version_id=None,
)


class _Uow:
    def __init__(self, students: list[UUID], member: StaffMember | None) -> None:
        self._students = students
        self._member = member
        self.courses = self
        self.staff = self
        self.enrollments = self

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def get(self, *args: UUID) -> Any:
        return COURSE if len(args) == 1 else self._member

    async def list_for_course(self, course_id: UUID) -> list[Enrollment]:
        return [
            Enrollment(id=new_id(), course_id=course_id, user_id=u, via="join")
            for u in self._students
        ]


def _usecase(students: list[UUID], member: StaffMember | None) -> ListBroadcastAudience:
    uow = _Uow(students, member)
    factory: Any = lambda: uow  # noqa: E731 - the use case wants a factory
    return ListBroadcastAudience(factory)


def _member(*permissions: str) -> StaffMember:
    return StaffMember(
        user_id=new_id(),
        role="teacher",
        permissions=frozenset(permissions),
        show_on_page=False,
        position=0,
    )


async def test_the_audience_is_the_enrolled_students() -> None:
    students = [new_id(), new_id()]
    teacher = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))

    audience = await _usecase(students, _member("publish")).execute(teacher, COURSE.id)

    assert set(audience.user_ids) == set(students)
    assert audience.slug == "algebra-9"


async def test_an_lms_admin_may_broadcast_without_a_staff_row() -> None:
    admin = Actor(user_id=new_id(), roles=frozenset({Role.LMS_ADMIN}))

    audience = await _usecase([new_id()], None).execute(admin, COURSE.id)

    assert len(audience.user_ids) == 1


@pytest.mark.parametrize("member", [None, "review", "view_drafts"])
async def test_a_stranger_or_a_reviewer_cannot_broadcast(member: str | None) -> None:
    actor = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
    staff = _member(member) if member else None

    with pytest.raises(CoursePermissionError):
        await _usecase([new_id()], staff).execute(actor, COURSE.id)
