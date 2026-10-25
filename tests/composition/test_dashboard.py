"""ADM-2: the Administration dashboard (GET /v1/admin/dashboard)."""

import datetime as dt
from typing import Any

from app.interfaces.http.v1.composition.ports import DayCounts
from app.shared.actor import Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of
from tests.composition.fakes import make_lesson

NOW = dt.datetime(2026, 10, 6, 9, 0, tzinfo=dt.UTC)


def sync_run() -> dict[str, Any]:
    return {
        "id": new_id(),
        "started_at": NOW - dt.timedelta(hours=1),
        "finished_at": NOW - dt.timedelta(minutes=50),
        "status": "ok",
        "stats": {"students": 120, "failed": 1},
    }


def broadcast(title: str) -> dict[str, Any]:
    return {
        "id": new_id(),
        "title": title,
        "text": "<b>Monday</b>",
        "media_file_ids": [],
        "audience": {"everyone": True, "roles": [], "group_ids": [], "semesters": []},
        "status": "scheduled",
        "scheduled_at": NOW + dt.timedelta(days=1),
        "created_via": "ui",
        "author": {"id": new_id(), "first_name": "Aziza", "last_name": "Karimova"},
        "stats": None,
        "created_at": NOW,
    }


async def test_today_counts_come_from_the_schedule(world: World) -> None:
    """ADM-2: today's lessons, cancelled ones and lessons without a teacher."""
    admin = world.add_user(Role.ADMIN)
    world.overview.counts = DayCounts(lessons=42, cancelled=3, teacher_needed=2)

    dashboard = await world.composition.build_admin_dashboard.execute(actor_of(admin))

    assert dashboard["today"] == {"lessons": 42, "cancelled": 3, "teacher_needed": 2}
    assert world.overview.count_days == [dt.date(2026, 10, 6)]


async def test_missing_attendance_is_counted_per_teacher_worst_first(
    world: World,
) -> None:
    """ADM-2: lessons of the last days without attendance."""
    admin = world.add_user(Role.ADMIN)
    worst = world.add_user(Role.TEACHER, first_name="Nodira", last_name="Aliyeva")
    other = world.add_user(Role.TEACHER, first_name="Anvar", last_name="Zokirov")
    tied = world.add_user(Role.TEACHER, first_name="Bahodir", last_name="Abdullayev")
    world.classwork.missing = [
        make_lesson(teacher_id=worst.id),
        make_lesson(teacher_id=worst.id),
        make_lesson(teacher_id=other.id),
        make_lesson(teacher_id=tied.id),
        make_lesson(teacher_id=None),
        make_lesson(teacher_id=new_id()),
    ]

    dashboard = await world.composition.build_admin_dashboard.execute(actor_of(admin))

    rows = [
        (r["teacher"]["last_name"], r["count"]) for r in dashboard["missing_attendance"]
    ]
    assert rows == [("Aliyeva", 2), ("Abdullayev", 1), ("Zokirov", 1)]
    assert dashboard["missing_attendance"][0]["teacher"]["id"] == worst.id


async def test_missing_attendance_looks_at_the_last_seven_days(world: World) -> None:
    """ACA-9: older gaps are history; the report covers all teachers."""
    admin = world.add_user(Role.ADMIN)

    await world.composition.build_admin_dashboard.execute(actor_of(admin))

    assert world.classwork.missing_calls == [
        (None, dt.date(2026, 9, 29), dt.date(2026, 10, 6))
    ]


async def test_sync_shows_the_last_run_and_the_accounts_needing_reauth(
    world: World,
) -> None:
    """ADM-2: EMIS sync status and accounts needing EMIS re-auth."""
    admin = world.add_user(Role.ADMIN)
    world.add_student(emis_status="needs_reauth")
    world.add_student(emis_status="needs_reauth")
    world.add_student(emis_status="active")
    world.add_student(emis_status="needs_reauth", status=UserStatus.BLOCKED)
    world.add_user(Role.TEACHER)
    world.sync.last_run = sync_run()

    dashboard = await world.composition.build_admin_dashboard.execute(actor_of(admin))

    assert dashboard["sync"]["needs_reauth"] == 2
    assert dashboard["sync"]["last_run"] == world.sync.last_run


async def test_sync_without_runs_has_no_last_run(world: World) -> None:
    """ADM-2: a fresh installation has no sync run yet."""
    admin = world.add_user(Role.ADMIN)

    dashboard = await world.composition.build_admin_dashboard.execute(actor_of(admin))

    assert dashboard["sync"] == {"last_run": None, "needs_reauth": 0}


async def test_scheduled_broadcasts_are_listed(world: World) -> None:
    """ADM-2: scheduled broadcasts."""
    admin = world.add_user(Role.ADMIN)
    world.broadcasts.items = [broadcast("Exams"), broadcast("Holiday")]

    dashboard = await world.composition.build_admin_dashboard.execute(actor_of(admin))

    assert [b["title"] for b in dashboard["scheduled_broadcasts"]] == [
        "Exams",
        "Holiday",
    ]
    assert world.broadcasts.limits == [20]


async def test_endpoint_returns_the_dashboard_with_contract_fields(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/dashboard: AdminDashboard."""
    admin = world.add_user(Role.ADMIN)
    teacher = world.add_user(Role.TEACHER, last_name="Aliyeva")
    world.overview.counts = DayCounts(lessons=5, cancelled=1, teacher_needed=0)
    world.classwork.missing = [make_lesson(teacher_id=teacher.id)]
    world.sync.last_run = sync_run()
    world.broadcasts.items = [broadcast("Exams")]
    client = await client_for(actor_of(admin))

    response = await client.get("/v1/admin/dashboard")

    assert response.status_code == 200
    body = response.json()
    assert set(body) == {"today", "missing_attendance", "sync", "scheduled_broadcasts"}
    assert body["today"] == {"lessons": 5, "cancelled": 1, "teacher_needed": 0}
    assert body["missing_attendance"][0]["count"] == 1
    assert set(body["sync"]["last_run"]) == {
        "id",
        "started_at",
        "finished_at",
        "status",
        "stats",
    }
    assert body["scheduled_broadcasts"][0]["status"] == "scheduled"


async def test_students_and_teachers_cannot_open_the_dashboard(
    world: World, client_for: ClientFor
) -> None:
    """ADM-2: Administration only."""
    student = world.add_student()
    teacher = world.add_user(Role.TEACHER)

    for caller in (student, teacher):
        client = await client_for(actor_of(caller))
        response = await client.get("/v1/admin/dashboard")
        assert response.status_code == 403
        assert response.json()["type"] == "common/forbidden"


async def test_the_dashboard_needs_a_login(client_for: ClientFor) -> None:
    """GET /v1/admin/dashboard without a token answers 401."""
    client = await client_for(None)

    response = await client.get("/v1/admin/dashboard")

    assert response.status_code == 401
