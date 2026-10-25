"""ADM-4: the teacher profile (GET /v1/admin/teachers/{id}/profile)."""

import datetime as dt

from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.data import account_detail, group_item, lesson_json


def fill_pages(world: World, teacher: UserRef) -> None:
    """Give the port fakes pages for the teacher."""
    world.accounts.detail = account_detail(teacher)
    world.teachers.timetable_data = [lesson_json(), lesson_json(period=3)]
    world.teachers.missing_data = [lesson_json(day=dt.date(2026, 10, 2))]
    world.teachers.groups_data = [group_item()]


async def test_the_profile_shows_the_week_the_gaps_and_the_curated_groups(
    world: World,
) -> None:
    """ADM-4: timetable and how many lessons lack attendance."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER, last_name="Aliyeva")
    fill_pages(world, teacher)

    profile = await world.composition.build_teacher_profile.execute(
        actor_of(admin), teacher.id, ip="10.0.0.1", user_agent="pytest"
    )

    assert profile["user"]["last_name"] == "Aliyeva"
    assert len(profile["timetable_week"]) == 2
    assert len(profile["missing_attendance"]) == 1
    assert profile["curated_groups"][0]["name"] == "2TN2"
    assert world.accounts.calls == [(admin.id, teacher.id, "10.0.0.1", "pytest")]


async def test_the_profile_carries_the_teachers_photo_link(world: World) -> None:
    """ADM-4: the photo the teacher uploaded, as on My Teachers; no photo gives null."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER)
    other = world.add_user(Role.TEACHER)
    fill_pages(world, teacher)
    world.identity.photos[teacher.id] = "https://files.example.test/photos/teacher.jpg"

    profile = await world.composition.build_teacher_profile.execute(
        actor_of(admin), teacher.id, ip=None, user_agent=None
    )
    without = await world.composition.build_teacher_profile.execute(
        actor_of(admin), other.id, ip=None, user_agent=None
    )

    assert profile["user"]["photo_url"] == (
        "https://files.example.test/photos/teacher.jpg"
    )
    assert without["user"]["photo_url"] is None


async def test_the_photo_link_survives_the_response_schema(
    world: World, client_for: ClientFor
) -> None:
    """ADM-4: the route answers with the photo link, not only the use case."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER)
    fill_pages(world, teacher)
    world.identity.photos[teacher.id] = "https://files.example.test/photos/teacher.jpg"
    client = await client_for(actor_of(admin))

    response = await client.get(f"/v1/admin/teachers/{teacher.id}/profile")

    assert response.status_code == 200
    assert response.json()["user"]["photo_url"] == (
        "https://files.example.test/photos/teacher.jpg"
    )


async def test_week_and_missing_attendance_windows(world: World) -> None:
    """ADM-4: this week Monday-Sunday; missing attendance of the last 7 days."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER)
    fill_pages(world, teacher)

    await world.composition.build_teacher_profile.execute(
        actor_of(admin), teacher.id, ip=None, user_agent=None
    )

    assert world.teachers.timetable_calls == [
        (teacher.id, dt.date(2026, 10, 5), dt.date(2026, 10, 11))
    ]
    assert world.teachers.missing_calls == [
        (teacher.id, dt.date(2026, 9, 29), dt.date(2026, 10, 6))
    ]


async def test_endpoint_returns_teacher_profile_with_contract_fields(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/teachers/{user_id}/profile: TeacherProfile."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER, last_name="Aliyeva")
    fill_pages(world, teacher)
    client = await client_for(actor_of(admin))

    response = await client.get(f"/v1/admin/teachers/{teacher.id}/profile")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "user",
        "timetable_week",
        "missing_attendance",
        "curated_groups",
    }
    assert "recent_audit" not in body["user"]
    assert body["user"]["roles"] == ["teacher"]
    assert body["curated_groups"][0]["students_count"] == 20


async def test_a_student_is_not_a_teacher(world: World, client_for: ClientFor) -> None:
    """ADM-4: the profile exists for teachers only."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    client = await client_for(actor_of(admin))

    response = await client.get(f"/v1/admin/teachers/{student.id}/profile")

    assert response.status_code == 404
    assert response.json()["type"] == "composition/teacher-not-found"


async def test_an_unknown_user_is_not_found(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/teachers/{user_id}/profile for a missing user."""
    admin = world.add_user(Role.ADMIN)
    client = await client_for(actor_of(admin))

    response = await client.get(f"/v1/admin/teachers/{new_id()}/profile")

    assert response.status_code == 404


async def test_teachers_cannot_read_each_others_profiles(
    world: World, client_for: ClientFor
) -> None:
    """ADM-4: Administration only."""
    teacher = world.add_user(Role.TEACHER)
    other = world.add_user(Role.TEACHER)
    client = await client_for(actor_of(teacher))

    response = await client.get(f"/v1/admin/teachers/{other.id}/profile")

    assert response.status_code == 403
