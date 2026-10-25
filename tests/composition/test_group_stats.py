"""ADM-6: attendance rate and average GPA per group (GET /v1/admin/groups/stats)."""

import datetime as dt

from app.shared.actor import Role
from app.shared.ids import new_id
from tests.composition.conftest import ClientFor, World, actor_of


async def test_attendance_rate_is_the_share_of_present_students(world: World) -> None:
    """ADM-6: the report counts absences; the page shows attendance."""
    admin = world.add_user(Role.ADMIN)
    group = new_id()
    world.overview.group_ids = [group]
    world.attendance.rates = {group: 0.0625}

    [row] = await world.composition.build_group_stats.execute(actor_of(admin))

    assert row == {"group_id": group, "attendance_rate": 0.9375, "average_gpa": None}


async def test_attendance_is_measured_from_the_term_start_to_today(
    world: World,
) -> None:
    """ADM-6: this term's attendance."""
    admin = world.add_user(Role.ADMIN)

    await world.composition.build_group_stats.execute(actor_of(admin))

    assert world.attendance.calls == [(dt.date(2026, 9, 2), dt.date(2026, 10, 6))]


async def test_a_term_that_has_not_started_has_no_attendance_yet(
    world: World,
) -> None:
    """ADM-6: no rate before the first lesson."""
    admin = world.add_user(Role.ADMIN)
    group = new_id()
    world.overview.group_ids = [group]
    world.overview.bounds = (dt.date(2027, 1, 20), dt.date(2027, 6, 1))
    world.attendance.rates = {group: 0.5}

    [row] = await world.composition.build_group_stats.execute(actor_of(admin))

    assert row["attendance_rate"] is None
    assert world.attendance.calls == []


async def test_without_a_term_there_is_no_attendance(world: World) -> None:
    """ADM-6: groups are listed even before a term exists."""
    admin = world.add_user(Role.ADMIN)
    group = new_id()
    world.overview.group_ids = [group]
    world.overview.bounds = None

    [row] = await world.composition.build_group_stats.execute(actor_of(admin))

    assert row["attendance_rate"] is None


async def test_average_gpa_ignores_students_without_a_gpa(world: World) -> None:
    """ADM-6: average GPA of the group's students that have one."""
    admin = world.add_user(Role.ADMIN)
    group = new_id()
    first, second, third = new_id(), new_id(), new_id()
    world.overview.group_ids = [group]
    world.schedule.group_users[group] = [first, second, third]
    world.marks.gpas = {first: 4.0, second: 3.5, third: None}

    [row] = await world.composition.build_group_stats.execute(actor_of(admin))

    assert row["average_gpa"] == 3.75
    assert world.marks.gpa_calls == [[first, second, third]]


async def test_a_group_without_students_has_no_gpa(world: World) -> None:
    """ADM-6: nothing to average."""
    admin = world.add_user(Role.ADMIN)
    world.overview.group_ids = [new_id()]

    [row] = await world.composition.build_group_stats.execute(actor_of(admin))

    assert row["average_gpa"] is None
    assert world.marks.gpa_calls == []


async def test_every_active_group_gets_a_row(world: World) -> None:
    """ADM-6: rows follow the group list."""
    admin = world.add_user(Role.ADMIN)
    first, second = new_id(), new_id()
    world.overview.group_ids = [first, second]
    world.attendance.rates = {first: 0.1}

    rows = await world.composition.build_group_stats.execute(actor_of(admin))

    assert [(r["group_id"], r["attendance_rate"]) for r in rows] == [
        (first, 0.9),
        (second, None),
    ]


async def test_endpoint_returns_group_id_attendance_rate_and_average_gpa(
    world: World, client_for: ClientFor
) -> None:
    """GET /v1/admin/groups/stats: {group_id, attendance_rate, average_gpa}[]."""
    admin = world.add_user(Role.ADMIN)
    group = new_id()
    world.overview.group_ids = [group]
    client = await client_for(actor_of(admin))

    response = await client.get("/v1/admin/groups/stats")

    assert response.status_code == 200
    assert response.json() == [
        {"group_id": str(group), "attendance_rate": None, "average_gpa": None}
    ]


async def test_students_cannot_read_group_stats(
    world: World, client_for: ClientFor
) -> None:
    """ADM-6: Administration only."""
    student = world.add_student()
    client = await client_for(actor_of(student))

    response = await client.get("/v1/admin/groups/stats")

    assert response.status_code == 403
