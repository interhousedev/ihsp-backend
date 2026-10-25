"""LMS-21, ADM-5: LMS admins manage the people who may create courses."""

from app.shared.actor import Role
from tests.identity.http.conftest import Api

CREATORS = "/v1/staff/lms/creators"


async def lms_admin(api: Api) -> None:
    """Sign in as a member of Administration who is also an LMS admin."""
    user = await api.world.add_user(
        roles={Role.ADMIN, Role.LMS_ADMIN},
        otp_enabled=True,
        login="lms.admin",
        recovery_email="lms@example.org",
    )
    api.login_as(user)


async def test_only_the_lms_admin_manages_course_creators(api: Api) -> None:
    """A plain admin, a teacher and a creator get 403 on all three routes."""
    target = await api.world.add_user(roles={Role.TEACHER}, login="t.target")
    plain_admin = await api.admin()
    teacher = await api.world.add_user(roles={Role.TEACHER}, login="t.other")
    creator = await api.world.add_user(
        roles={Role.TEACHER, Role.LMS_CREATOR}, login="t.creator"
    )

    for actor in (plain_admin, api.login_as(teacher), api.login_as(creator)):
        api.holder["actor"] = actor
        listed = await api.client.get(CREATORS)
        added = await api.client.put(f"{CREATORS}/{target.id}")
        removed = await api.client.delete(f"{CREATORS}/{target.id}")

        assert {listed.status_code, added.status_code, removed.status_code} == {403}
    assert api.world.user(target.id).roles == {Role.TEACHER}


async def test_the_lms_admin_grants_lists_and_revokes_the_creator_role(
    api: Api,
) -> None:
    """The whole round trip, audited with the LMS admin as the actor."""
    await lms_admin(api)
    teacher = await api.world.add_user(
        roles={Role.TEACHER}, login="t.new", first_name="Bobur", last_name="Usmonov"
    )
    api.world.add_session(teacher)

    added = await api.client.put(f"{CREATORS}/{teacher.id}")
    again = await api.client.put(f"{CREATORS}/{teacher.id}")
    listed = await api.client.get(CREATORS)
    removed = await api.client.delete(f"{CREATORS}/{teacher.id}")
    after = await api.client.get(CREATORS)

    assert added.status_code == 200
    assert added.json()["id"] == str(teacher.id)
    assert added.json()["login"] == "t.new"
    assert again.status_code == 200
    assert [item["id"] for item in listed.json()["items"]] == [str(teacher.id)]
    assert removed.status_code == 204
    assert after.json()["items"] == []
    assert api.world.user(teacher.id).roles == {Role.TEACHER}
    events = [a for a in api.world.store.audits if a.user_id == teacher.id]
    assert [(a.type, (a.metadata or {})["role"]) for a in events] == [
        ("role.granted", "lms_creator"),
        ("role.revoked", "lms_creator"),
    ]
    assert all(a.actor_id != teacher.id for a in events)


async def test_students_cannot_become_course_creators(api: Api) -> None:
    """422 `id/course-creator-not-staff`; the student keeps the same roles."""
    await lms_admin(api)
    student = await api.world.add_user(roles={Role.STUDENT}, login="s.no")

    response = await api.client.put(f"{CREATORS}/{student.id}")

    assert response.status_code == 422
    assert response.json()["type"] == "id/course-creator-not-staff"
    assert api.world.user(student.id).roles == {Role.STUDENT}


async def test_an_unknown_user_is_404_and_a_member_of_administration_is_fine(
    api: Api,
) -> None:
    """The role can sit on an admin too."""
    await lms_admin(api)
    other_admin = await api.world.add_user(roles={Role.ADMIN}, login="a.other")

    missing = await api.client.put(f"{CREATORS}/00000000-0000-0000-0000-0000000000aa")
    granted = await api.client.put(f"{CREATORS}/{other_admin.id}")

    assert missing.status_code == 404
    assert granted.status_code == 200
    assert api.world.user(other_admin.id).roles == {Role.ADMIN, Role.LMS_CREATOR}
