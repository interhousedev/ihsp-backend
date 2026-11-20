"""Admission access stacks by role, over real HTTP and PostgreSQL.

A user who is also a student reaches the student side whatever other roles the
account holds; a user without the student role (and no entitlement) does not.
"""

from collections.abc import AsyncIterator, Iterator

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.interfaces.http.dependencies import get_actor
from app.modules.admission.infrastructure.orm._common import SCHEMA
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.ids import new_id
from tests.integration.conftest import ContainerFactory

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

STUDENT_SIDE = (
    "/v1/admission/list",
    "/v1/admission/list/insights",
    "/v1/admission/outcomes",
    "/v1/admission/me/profile",
    "/v1/admission/readiness",
    "/v1/admission/calendar?from=2026-11-01&to=2026-12-01",
    "/v1/admission/test-scores",
)
MIXED = frozenset(
    {Role.ADMIN, Role.LIBRARIAN, Role.LMS_ADMIN, Role.LMS_CREATOR, Role.STUDENT}
)


@pytest_asyncio.fixture(autouse=True)
async def clean_admission(engine: AsyncEngine) -> AsyncIterator[None]:
    """The shared cleanup skips the admission schema: empty it after the test."""
    yield
    async with engine.begin() as conn:
        tables = await conn.execute(
            text(
                "SELECT quote_ident(schemaname) || '.' || quote_ident(tablename) "
                "FROM pg_tables WHERE schemaname = :schema"
            ),
            {"schema": SCHEMA},
        )
        names = ", ".join(row[0] for row in tables)
        if names:
            await conn.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))


@pytest.fixture
def apps() -> Iterator[list[FastAPI]]:
    """Drop the actor overrides of every app a test built."""
    built: list[FastAPI] = []
    yield built
    for app in built:
        app.dependency_overrides.clear()


async def _client(
    make_container: ContainerFactory, apps: list[FastAPI], roles: frozenset[Role]
) -> AsyncClient:
    container: Container = await make_container("all")
    auth = container.identity.auth
    user = User(
        id=new_id(),
        first_name="Role",
        last_name="Stack",
        login=f"stack{new_id().hex[:8]}",
        password_hash=await auth.hasher.hash("Secret-Passw0rd!"),
        roles=set(roles),
        recovery_email="stack@example.org",
        recovery_email_verified_at=container.clock.now(),
        status=UserStatus.ACTIVE,
        preferences={"locale": "ru"},
    )
    async with auth.uow_factory() as uow:
        await uow.users.add(user)
        await uow.commit()
    actor = Actor(user_id=user.id, roles=roles)
    app = build_http_app(container, process="all")
    app.dependency_overrides[get_actor] = lambda: actor
    apps.append(app)
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


@pytest.mark.parametrize(
    "roles", [frozenset({Role.STUDENT}), MIXED], ids=["student", "mixed"]
)
async def test_student_side_opens_for_any_student(
    make_container: ContainerFactory,
    apps: list[FastAPI],
    roles: frozenset[Role],
) -> None:
    async with await _client(make_container, apps, roles) as client:
        me = (await client.get("/v1/admission/me")).json()
        assert me["kind"] == "applicant", me
        failures = {
            path: (r.status_code, r.text[:200])
            for path in STUDENT_SIDE
            if (r := await client.get(path)).status_code != 200
        }
    assert failures == {}


async def test_staff_without_student_role_is_kept_off_the_student_side(
    make_container: ContainerFactory, apps: list[FastAPI]
) -> None:
    roles = frozenset({Role.ADMIN, Role.LIBRARIAN, Role.LMS_ADMIN})
    async with await _client(make_container, apps, roles) as client:
        me = (await client.get("/v1/admission/me")).json()
        assert me["kind"] == "staff", me
        codes = {path: (await client.get(path)).status_code for path in STUDENT_SIDE}
    assert set(codes.values()) <= {403, 404}, codes


async def test_non_student_non_staff_cannot_enter(
    make_container: ContainerFactory, apps: list[FastAPI]
) -> None:
    async with await _client(make_container, apps, frozenset({Role.TEACHER})) as c:
        me = (await c.get("/v1/admission/me")).json()
        assert me["kind"] == "none", me
        codes = {path: (await c.get(path)).status_code for path in STUDENT_SIDE}
    assert set(codes.values()) <= {403, 404}, codes
