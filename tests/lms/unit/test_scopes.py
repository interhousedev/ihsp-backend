"""LMS scopes narrow roles: course scopes for the course, modules for modules."""

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from app.modules.lms.application.authoring.archive_course import ArchiveCourse
from app.modules.lms.domain.authoring.entities import Course, StaffMember
from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import CoursePermissionError
from app.modules.lms.domain.authoring.permissions import (
    EDIT,
    PERMISSIONS,
    CourseAccess,
)
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from app.shared.lms_scopes import (
    COURSES_DELETE,
    COURSES_READ,
    COURSES_WRITE,
    MODULES_WRITE,
    effective_scopes,
    scope_allows,
)

import pytest


def _actor(*scopes: str, roles: frozenset[Role] | None = None) -> Actor:
    return Actor(
        user_id=new_id(),
        roles=roles or frozenset({Role.TEACHER}),
        scopes=frozenset(scopes),
    )


def _owner(actor: Actor) -> StaffMember:
    return StaffMember(
        course_id=new_id(),
        user_id=actor.user_id,
        role="owner",
        permissions=sorted(PERMISSIONS),
        show_on_page=False,
        position=0,
        added_by=actor.user_id,
    )


def test_modules_scope_cannot_edit_course_title() -> None:
    actor = _actor(MODULES_WRITE)
    access = CourseAccess(actor=actor, staff=_owner(actor))

    access.require(EDIT)  # the role is fine ...
    with pytest.raises(CoursePermissionError):
        access.require_scope(COURSES_WRITE)  # ... the token is not


def test_modules_scope_can_edit_modules_and_steps() -> None:
    actor = _actor(MODULES_WRITE)
    CourseAccess(actor=actor, staff=_owner(actor)).require_scope(MODULES_WRITE)


def test_course_write_scope_alone_cannot_edit_modules() -> None:
    actor = _actor(COURSES_WRITE)
    with pytest.raises(CoursePermissionError):
        CourseAccess(actor=actor, staff=_owner(actor)).require_scope(MODULES_WRITE)


def test_an_lms_admin_is_still_bound_by_the_token_scopes() -> None:
    actor = _actor(MODULES_WRITE, roles=frozenset({Role.LMS_ADMIN}))
    access = CourseAccess(actor=actor, staff=None)

    assert access.can(EDIT)
    with pytest.raises(CoursePermissionError):
        access.require_scope(COURSES_DELETE)


def test_a_browser_session_has_no_scopes_and_is_not_limited() -> None:
    actor = _actor()
    access = CourseAccess(actor=actor, staff=_owner(actor))
    for scope in (COURSES_WRITE, COURSES_DELETE, MODULES_WRITE):
        access.require_scope(scope)
    access.require_read_scope()


def test_any_lms_scope_reads_but_a_foreign_scope_does_not() -> None:
    CourseAccess(actor=_actor(MODULES_WRITE), staff=None).require_read_scope()
    with pytest.raises(CoursePermissionError):
        CourseAccess(actor=_actor("marks:read"), staff=None).require_read_scope()


def test_pre_split_scope_names_keep_their_meaning() -> None:
    assert effective_scopes({"courses:read"}) >= {COURSES_READ}
    assert scope_allows({"courses:draft"}, MODULES_WRITE)
    assert not scope_allows({"courses:draft"}, COURSES_WRITE)


class _Courses:
    def __init__(self, course: Course) -> None:
        self.course = course
        self.saved = 0

    async def get_locked(self, course_id: UUID) -> Course | None:
        return self.course

    async def save(self, course: Course) -> None:
        self.saved += 1


class _Staff:
    def __init__(self, member: StaffMember | None) -> None:
        self.member = member

    async def get(self, course_id: UUID, user_id: UUID) -> StaffMember | None:
        return self.member


class _Uow:
    def __init__(self, course: Course, member: StaffMember | None) -> None:
        self.courses = _Courses(course)
        self.staff = _Staff(member)
        self.commits = 0

    async def __aenter__(self) -> "_Uow":
        return self

    async def __aexit__(self, *exc: Any) -> None:
        return None

    async def commit(self) -> None:
        self.commits += 1


def _archive(uow: _Uow) -> ArchiveCourse:
    factory: Any = lambda: uow  # noqa: E731 - the use case wants a factory
    return ArchiveCourse(factory)


def _course() -> Course:
    return Course(
        id=new_id(),
        slug="algebra-1",
        title="Algebra",
        description="",
        visibility=Visibility.PUBLIC,
        status=CourseStatus.ACTIVE,
        created_by=new_id(),
        draft_meta={},
        draft_outline={"sections": []},
        outline_hash="h",
        draft_updated_at=datetime.now(UTC),
    )


async def test_delete_needs_the_delete_scope_and_archives_the_course() -> None:
    owner = _actor(COURSES_READ, COURSES_DELETE)
    course = _course()
    uow = _Uow(course, _owner(owner))

    status = await _archive(uow).execute(owner, course.id)

    assert status is CourseStatus.ARCHIVED
    assert uow.courses.saved == 1 and uow.commits == 1


async def test_delete_without_the_delete_scope_changes_nothing() -> None:
    limited = _actor(COURSES_READ, COURSES_WRITE, MODULES_WRITE)
    course = _course()
    uow = _Uow(course, _owner(limited))

    with pytest.raises(CoursePermissionError):
        await _archive(uow).execute(limited, course.id)

    assert course.status is CourseStatus.ACTIVE
    assert uow.courses.saved == 0


async def test_only_the_owner_may_delete() -> None:
    teacher = _actor(COURSES_DELETE)
    member = _owner(teacher)
    member.permissions = [EDIT]
    course = _course()

    with pytest.raises(CoursePermissionError):
        await _archive(_Uow(course, member)).execute(teacher, course.id)
