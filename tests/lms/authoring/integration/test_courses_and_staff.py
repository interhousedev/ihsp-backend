"""LMS-3, LMS-5, LMS-21, UF-LMS-06, UF-LMS-07: courses and course staff."""

from collections.abc import Callable
from uuid import UUID

from app.modules.lms.domain.authoring.enums import CourseStatus, Visibility
from app.modules.lms.domain.authoring.errors import (
    CoursePermissionError,
    FileMissingError,
    InviteNotApplicableError,
    LastManagerError,
    SlugInvalidError,
    SlugTakenError,
    StaffAlreadyExistsError,
    StaffMemberNotFoundError,
    UserNotFoundError,
)
from app.modules.lms.domain.authoring.unset import UNSET
from app.modules.lms.wiring_authoring import AuthoringServices
from app.shared.actor import Actor, Role
from app.shared.base_error import ForbiddenError
from tests.fakes.lms.files import FakeFilesApi
from tests.fakes.lms.identity import FakeIdentityDirectory
from tests.lms.authoring.conftest import CourseFixture

import pytest


async def test_lms_admin_creates_a_course_with_an_empty_unpublished_draft(
    services: AuthoringServices, admin: Actor
) -> None:
    """LMS-21, UF-LMS-06: a new course has an empty draft and no live version."""
    created = await services.create_course.execute(
        admin, title="  Algebra  ", slug="algebra-1", visibility=Visibility.PUBLIC
    )

    assert created.title == "Algebra"
    assert created.slug == "algebra-1"
    assert created.outline == []
    assert created.live_version is None
    assert created.invite_code is None
    assert created.lock_version == 0
    assert created.draft_seq == 0
    assert created.my_permissions == [
        "edit",
        "publish",
        "review",
        "manage_staff",
        "view_drafts",
    ]


async def test_only_the_lms_admin_and_course_creators_create_courses(
    services: AuthoringServices, make_actor: Callable[..., Actor]
) -> None:
    """LMS-21: a teacher or a student alone cannot create courses."""
    for role in (Role.TEACHER, Role.STUDENT, Role.ADMIN):
        with pytest.raises(ForbiddenError):
            await services.create_course.execute(
                make_actor(role),
                title="Algebra",
                slug="algebra",
                visibility=Visibility.PUBLIC,
            )


async def test_a_course_creator_owns_the_course_they_create(
    services: AuthoringServices,
    identity: FakeIdentityDirectory,
    make_actor: Callable[..., Actor],
) -> None:
    """LMS-21: the creator gets an `owner` row with every permission."""
    creator = make_actor(Role.TEACHER, Role.LMS_CREATOR)
    identity.add_user("creator", user_id=creator.user_id, roles=[Role.LMS_CREATOR])

    created = await services.create_course.execute(
        creator, title="Algebra", slug="algebra-own", visibility=Visibility.PUBLIC
    )
    staff = await services.list_course_staff.execute(creator, created.id)
    mine = await services.queries.courses_for_staff(creator.user_id, "edit")

    assert created.my_permissions == [
        "edit",
        "publish",
        "review",
        "manage_staff",
        "view_drafts",
    ]
    assert [(i.user.id, i.role, i.show_on_page) for i in staff] == [
        (creator.user_id, "owner", False)
    ]
    assert [c["slug"] for c in mine] == ["algebra-own"]


async def test_an_lms_admin_creating_a_course_gets_no_staff_row(
    services: AuthoringServices, admin: Actor
) -> None:
    """The admin already holds every permission on every course."""
    created = await services.create_course.execute(
        admin, title="Algebra", slug="algebra-adm", visibility=Visibility.PUBLIC
    )

    assert await services.list_course_staff.execute(admin, created.id) == []


async def test_a_course_creator_works_only_on_own_and_shared_courses(
    services: AuthoringServices,
    identity: FakeIdentityDirectory,
    make_actor: Callable[..., Actor],
    course: CourseFixture,
) -> None:
    """Creators see and edit their own courses and those they were added to."""
    creator = make_actor(Role.TEACHER, Role.LMS_CREATOR)
    friend = make_actor(Role.TEACHER, Role.LMS_CREATOR)
    identity.add_user("creator", user_id=creator.user_id, roles=[Role.LMS_CREATOR])
    identity.add_user("friend", user_id=friend.user_id, roles=[Role.LMS_CREATOR])
    mine = await services.create_course.execute(
        creator, title="Mine", slug="mine-1", visibility=Visibility.PUBLIC
    )
    await services.create_course.execute(
        friend, title="Theirs", slug="theirs-1", visibility=Visibility.PUBLIC
    )

    with pytest.raises(CoursePermissionError):
        await services.update_course_settings.execute(
            friend, mine.id, status=CourseStatus.ARCHIVED
        )
    with pytest.raises(CoursePermissionError):
        await services.update_course_settings.execute(
            creator, course.id, status=CourseStatus.ARCHIVED
        )
    await services.add_course_staff.execute(
        creator, mine.id, login="friend", role="Teacher", permissions=None
    )
    shared = await services.update_course_settings.execute(
        friend, mine.id, status=CourseStatus.ARCHIVED
    )
    queries = services.queries
    creator_sees = await queries.courses_for_staff(creator.user_id, "edit")
    friend_sees = await queries.courses_for_staff(friend.user_id, "edit")

    assert shared.status == "archived"
    assert [c["slug"] for c in creator_sees] == ["mine-1"]
    assert sorted(c["slug"] for c in friend_sees) == ["mine-1", "theirs-1"]


async def test_slug_must_be_valid_and_unique(
    services: AuthoringServices, admin: Actor
) -> None:
    """Slugs are `[a-z0-9-]{3,60}` and unique."""
    await services.create_course.execute(
        admin, title="One", slug="algebra", visibility=Visibility.PUBLIC
    )

    with pytest.raises(SlugTakenError):
        await services.create_course.execute(
            admin, title="Two", slug="algebra", visibility=Visibility.PUBLIC
        )
    with pytest.raises(SlugInvalidError):
        await services.create_course.execute(
            admin, title="Three", slug="Not Valid", visibility=Visibility.PUBLIC
        )


async def test_invite_only_course_has_a_rotating_invite_code(
    services: AuthoringServices, admin: Actor
) -> None:
    """LMS-3: invite-only courses have a 10-character code that can be rotated."""
    created = await services.create_course.execute(
        admin, title="Secret", slug="secret", visibility=Visibility.INVITE
    )

    rotated = await services.rotate_invite_code.execute(admin, created.id)

    assert created.invite_code is not None and len(created.invite_code) == 10
    assert len(rotated.invite_code) == 10
    assert rotated.invite_code != created.invite_code
    draft = await services.get_course_draft.execute(admin, created.id)
    assert draft.invite_code == rotated.invite_code


async def test_public_course_has_no_invite_code_to_rotate(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """Only invite-only courses have a code."""
    with pytest.raises(InviteNotApplicableError):
        await services.rotate_invite_code.execute(course.team.owner, course.id)


async def test_changing_visibility_creates_or_drops_the_invite_code(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-3: a course switched to invite-only gets a code; public ones lose it."""
    owner = course.team.owner

    invite = await services.update_course_settings.execute(
        owner, course.id, visibility=Visibility.INVITE
    )
    public = await services.update_course_settings.execute(
        owner, course.id, visibility=Visibility.PUBLIC
    )

    assert invite.visibility == "invite" and invite.invite_code
    assert public.visibility == "public" and public.invite_code is None


async def test_course_settings_change_status_and_cover(
    services: AuthoringServices, course: CourseFixture, files: FakeFilesApi
) -> None:
    """The cover must be an existing file; `None` removes it."""
    owner = course.team.owner
    cover = files.add_file()

    archived = await services.update_course_settings.execute(
        owner, course.id, status=CourseStatus.ARCHIVED, cover_file_id=cover.id
    )
    cleared = await services.update_course_settings.execute(
        owner, course.id, cover_file_id=None
    )

    assert archived.status == "archived"
    assert cleared.status == "archived"
    with pytest.raises(FileMissingError):
        await services.update_course_settings.execute(
            owner, course.id, cover_file_id=UUID(int=1)
        )
    untouched = await services.update_course_settings.execute(
        owner, course.id, cover_file_id=UNSET
    )
    assert untouched.status == "archived"


async def test_settings_need_the_edit_permission(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """A tester cannot change settings."""
    with pytest.raises(CoursePermissionError):
        await services.update_course_settings.execute(
            course.team.tester, course.id, status=CourseStatus.ARCHIVED
        )


async def test_staff_are_added_by_login_with_preset_permissions(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-5, UF-LMS-06: role presets fill the permissions."""
    staff = {
        i.role: i
        for i in await services.list_course_staff.execute(course.team.admin, course.id)
    }

    assert staff["Owner"].permissions == [
        "edit",
        "publish",
        "review",
        "manage_staff",
        "view_drafts",
    ]
    assert staff["Teacher"].permissions == ["edit", "publish", "review", "view_drafts"]
    assert staff["Tester"].permissions == ["view_drafts"]
    assert staff["Reviewer"].permissions == ["review"]


async def test_staff_with_a_custom_role_and_explicit_permissions(
    services: AuthoringServices,
    course: CourseFixture,
    identity: FakeIdentityDirectory,
) -> None:
    """LMS-5: the role is free text; permissions are chosen one by one."""
    identity.add_user("madina", first_name="Madina", last_name="Aliyeva")

    item = await services.add_course_staff.execute(
        course.team.owner,
        course.id,
        login="MADINA",
        role="Assistant teacher",
        permissions=["edit", "review"],
        show_on_page=True,
        position=3,
    )

    assert item.role == "Assistant teacher"
    assert item.permissions == ["edit", "review"]
    assert (item.user.first_name, item.user.last_name) == ("Madina", "Aliyeva")
    assert item.position == 3


async def test_unknown_login_is_user_not_found(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The contract error `id/user-not-found` (404) for an unknown login."""
    with pytest.raises(UserNotFoundError) as caught:
        await services.add_course_staff.execute(
            course.team.owner,
            course.id,
            login="nobody",
            role="Tester",
            permissions=None,
        )

    assert caught.value.code == "id/user-not-found"
    assert caught.value.status == 404


async def test_a_person_cannot_be_added_twice(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """One staff row per person."""
    with pytest.raises(StaffAlreadyExistsError):
        await services.add_course_staff.execute(
            course.team.owner,
            course.id,
            login="tester",
            role="Tester",
            permissions=None,
        )


async def test_only_manage_staff_or_the_lms_admin_manage_staff(
    services: AuthoringServices,
    course: CourseFixture,
    identity: FakeIdentityDirectory,
) -> None:
    """LMS-5: a teacher without `manage_staff` cannot add people."""
    identity.add_user("newbie")

    with pytest.raises(CoursePermissionError):
        await services.add_course_staff.execute(
            course.team.teacher,
            course.id,
            login="newbie",
            role="Tester",
            permissions=None,
        )
    added = await services.add_course_staff.execute(
        course.team.admin, course.id, login="newbie", role="Tester", permissions=None
    )
    assert added.permissions == ["view_drafts"]


async def test_the_last_manager_cannot_be_removed_by_staff(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-07 2a: only the LMS admin may remove the last `manage_staff` holder."""
    owner = course.team.owner

    with pytest.raises(LastManagerError):
        await services.remove_course_staff.execute(owner, course.id, owner.user_id)
    with pytest.raises(LastManagerError):
        await services.update_course_staff.execute(
            owner, course.id, owner.user_id, permissions=["edit"]
        )
    await services.remove_course_staff.execute(
        course.team.admin, course.id, owner.user_id
    )


async def test_a_manager_can_leave_when_another_manager_exists(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """The rule only protects the last manager."""
    owner, teacher = course.team.owner, course.team.teacher
    await services.update_course_staff.execute(
        owner, course.id, teacher.user_id, permissions=["edit", "manage_staff"]
    )

    await services.remove_course_staff.execute(teacher, course.id, owner.user_id)

    remaining = await services.list_course_staff.execute(teacher, course.id)
    assert owner.user_id not in {i.user.id for i in remaining}


async def test_removed_staff_lose_access_at_once(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """UF-LMS-07 3: changes apply at once."""
    tester = course.team.tester
    await services.get_course_draft.execute(tester, course.id)

    await services.remove_course_staff.execute(
        course.team.owner, course.id, tester.user_id
    )

    with pytest.raises(CoursePermissionError):
        await services.get_course_draft.execute(tester, course.id)


async def test_staff_update_changes_only_the_given_fields(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """PATCH is partial."""
    tester = course.team.tester

    item = await services.update_course_staff.execute(
        course.team.owner, course.id, tester.user_id, role="QA", position=2
    )

    assert (item.role, item.position, item.permissions) == ("QA", 2, ["view_drafts"])
    with pytest.raises(StaffMemberNotFoundError):
        await services.update_course_staff.execute(
            course.team.owner, course.id, course.team.outsider.user_id, role="x"
        )


async def test_every_staff_member_reads_the_staff_list_but_outsiders_do_not(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """LMS-4: staff see the team; people outside the team do not."""
    items = await services.list_course_staff.execute(course.team.reviewer, course.id)

    assert len(items) == 4
    with pytest.raises(CoursePermissionError):
        await services.list_course_staff.execute(course.team.outsider, course.id)


async def test_courses_for_staff_follow_permissions_and_admins_see_all(
    services: AuthoringServices, course: CourseFixture
) -> None:
    """MCP: the course picker lists courses where the user can act."""
    queries = services.queries

    as_teacher = await queries.courses_for_staff(course.team.teacher.user_id, "edit")
    as_tester = await queries.courses_for_staff(course.team.tester.user_id, "edit")
    as_admin = await queries.courses_for_staff(course.team.admin.user_id, "edit")

    assert [c["slug"] for c in as_teacher] == ["calculus"]
    assert as_tester == []
    assert [c["slug"] for c in as_admin] == ["calculus"]
    assert as_teacher[0]["published"] is False
