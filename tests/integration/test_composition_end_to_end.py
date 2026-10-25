"""Composition endpoints over the real container and the seeded demo school."""

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.bootstrap.seed.users import ADMIN_LOGIN
from app.bootstrap.seed_demo import seed
from app.interfaces.http.dependencies import get_actor
from app.shared.actor import Actor, Role
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

STUDENT_LOGIN = "abdullayev.alisher"  # EMIS student01 of the fake EMIS


async def _actor(container: Container, login: str, role: Role) -> Actor:
    user = await container.identity.directory.user_by_login(login)
    assert user is not None, login
    return Actor(user_id=user.id, roles=frozenset({role}))


@pytest.fixture
async def seeded(
    make_container: ContainerFactory, world: IntegrationWorld
) -> tuple[FastAPI, Container]:
    """The `all` app over a container whose database holds the demo school."""
    container = await make_container("all")
    await seed(container, world.credentials)
    return build_http_app(container, process="all"), container


async def test_admin_dashboard_and_group_stats(
    seeded: tuple[FastAPI, Container],
) -> None:
    """ADM-2: the dashboard and the group statistics come from the real modules."""
    app, container = seeded
    admin = await _actor(container, ADMIN_LOGIN, Role.ADMIN)
    app.dependency_overrides[get_actor] = lambda: admin

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        dashboard = await client.get("/v1/admin/dashboard")
        stats = await client.get("/v1/admin/groups/stats")

    assert dashboard.status_code == 200, dashboard.text
    assert {"today", "missing_attendance"} <= set(dashboard.json())
    assert stats.status_code == 200, stats.text
    assert {row["group_id"] for row in stats.json()} and all(
        {"attendance_rate", "average_gpa"} <= set(row) for row in stats.json()
    )


async def test_student_gets_alerts_and_a_working_calendar_feed(
    seeded: tuple[FastAPI, Container],
) -> None:
    """WEB-4, WEB-6: alerts list, calendar token, iCal feed with the timetable."""
    app, container = seeded
    student = await _actor(container, STUDENT_LOGIN, Role.STUDENT)
    app.dependency_overrides[get_actor] = lambda: student

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        alerts = await client.get("/v1/me/alerts")
        issued = await client.post("/v1/me/calendar-token")
        url = issued.json()["url"]
        feed = await client.get(url.removeprefix(container.settings.urls.api))
        admin_route = await client.get("/v1/admin/dashboard")

    assert alerts.status_code == 200 and isinstance(alerts.json(), list)
    assert issued.status_code in (200, 201), issued.text
    assert feed.status_code == 200
    assert feed.headers["content-type"].startswith("text/calendar")
    assert "BEGIN:VEVENT" in feed.text
    assert admin_route.status_code == 403  # a student cannot read the dashboard
