"""ADM-3: the student profile of Administration (GET /v1/admin/students/{id})."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.composition.errors import StudentNotFoundError
from app.shared.actor import Role
from app.shared.contracts.identity import UserRef
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.data import (
    account_detail,
    lesson_json,
    semester_grades,
    student_attendance,
    student_profile,
)

import pytest


def fill_pages(world: World, student: UserRef, admin_id: UUID) -> None:
    """Give the port fakes pages for the student."""
    world.students.profile_data = student_profile(student)
    world.students.timetable_data = [lesson_json(), lesson_json(period=2)]
    world.students.grades_data = semester_grades()
    world.students.attendance_data = student_attendance()
    world.accounts.detail = account_detail(student, actor_id=admin_id)


async def test_everything_about_the_student_is_in_one_view(world: World) -> None:
    """ADM-3: profile, timetable, grades, attendance, Telegram, sessions, audit."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    fill_pages(world, student, admin.id)

    view = await world.composition.build_student_360.execute(
        actor_of(admin), student.id, ip="10.0.0.1", user_agent="pytest"
    )

    assert view["profile"]["user_id"] == student.id
    assert len(view["timetable_week"]) == 2
    assert view["grades"]["gpa"] == 4.2
    assert view["attendance"]["not_taken"] == 2
    assert [t["telegram_user_id"] for t in view["telegram"]] == [424242]
    assert len(view["sessions"]) == 1
    assert [a["type"] for a in view["audit"]] == ["student.viewed"]


async def test_the_profile_carries_the_account_status_and_roles(world: World) -> None:
    """ADM-3: Student360.profile = StudentProfile + status + roles."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    fill_pages(world, student, admin.id)

    view = await world.composition.build_student_360.execute(
        actor_of(admin), student.id, ip=None, user_agent=None
    )

    assert view["profile"]["status"] == "active"
    assert view["profile"]["roles"] == ["student"]


async def test_the_timetable_is_the_current_week_from_monday_to_sunday(
    world: World,
) -> None:
    """ADM-3: 2026-10-06 is a Tuesday."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    fill_pages(world, student, admin.id)

    await world.composition.build_student_360.execute(
        actor_of(admin), student.id, ip=None, user_agent=None
    )

    assert world.students.timetable_calls == [
        (student.id, dt.date(2026, 10, 5), dt.date(2026, 10, 11))
    ]


async def test_the_view_is_recorded_through_the_account_port_with_ip_and_agent(
    world: World,
) -> None:
    """GEN-6: opening a student's profile is audited by identity (student.viewed)."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    fill_pages(world, student, admin.id)

    await world.composition.build_student_360.execute(
        actor_of(admin), student.id, ip="10.0.0.1", user_agent="pytest"
    )

    assert world.accounts.calls == [(admin.id, student.id, "10.0.0.1", "pytest")]


async def test_a_user_without_a_student_record_is_not_found(world: World) -> None:
    """ADM-3: only students have this view; nothing is audited."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER)

    for user_id in (teacher.id, new_id()):
        with pytest.raises(StudentNotFoundError):
            await world.composition.build_student_360.execute(
                actor_of(admin), user_id, ip=None, user_agent=None
            )

    assert world.accounts.calls == []


async def test_endpoint_returns_student_360_with_contract_fields(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/students/{user_id}: Student360 (attendance keeps `from`/`to`)."""
    admin = world.add_user(Role.ADMIN)
    student = world.add_student()
    fill_pages(world, student, admin.id)
    client = await client_for(actor_of(admin))

    response = await client.get(
        f"/v1/admin/students/{student.id}", headers={"user-agent": "pytest-agent"}
    )

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {
        "profile",
        "timetable_week",
        "grades",
        "attendance",
        "telegram",
        "sessions",
        "audit",
    }
    assert {"from", "to", "summary", "days", "missed", "not_taken"} == set(
        body["attendance"]
    )
    assert body["attendance"]["from"] == "2026-09-02"
    assert body["profile"]["group"]["name"] == "2TN2"
    assert body["audit"][0]["actor"]["last_name"] == "Admin"
    [call] = world.accounts.calls
    assert call[3] == "pytest-agent"


async def test_an_unknown_student_answers_404_problem(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/students/{user_id} for a non-student."""
    admin = world.add_user(Role.ADMIN)
    client = await client_for(actor_of(admin))

    response = await client.get(f"/v1/admin/students/{new_id()}")

    assert response.status_code == 404
    assert response.json()["type"] == "composition/student-not-found"


async def test_a_student_cannot_open_another_students_profile(
    world: World, client_for: ClientFor
) -> None:
    """ADM-3: Administration only."""
    student = world.add_student()
    other = world.add_student(last_name="Rahimov")
    client = await client_for(actor_of(student))

    response = await client.get(f"/v1/admin/students/{other.id}")

    assert response.status_code == 403
    assert world.accounts.calls == []


async def test_a_teacher_cannot_open_a_student_profile(
    world: World, client_for: ClientFor
) -> None:
    """ADM-3: Administration only."""
    teacher = world.add_user(Role.TEACHER)
    student = world.add_student()
    client = await client_for(actor_of(teacher))

    response = await client.get(f"/v1/admin/students/{student.id}")

    assert response.status_code == 403


async def test_the_student_view_needs_a_login(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/students/{user_id} without a token answers 401."""
    client = await client_for(None)

    response = await client.get(f"/v1/admin/students/{new_id()}")

    assert response.status_code == 401
