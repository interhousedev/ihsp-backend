from collections.abc import AsyncIterator, Iterator
from uuid import UUID

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


async def test_certificates_feed_tests_and_honor_suggestions(
    make_container: ContainerFactory, apps: list[FastAPI]
) -> None:
    container: Container = await make_container("all")
    roles = frozenset({Role.STUDENT})
    async with await _client(make_container, apps, roles) as client:
        me = (await client.get("/v1/admission/me")).json()
        student = UUID(me["user_id"]) if "user_id" in me else None
        if student is None:
            student = next(iter(apps[-1].dependency_overrides.values()))().user_id
        name = {"uz": "x", "ru": "x", "en": "Exam"}
        exam = await container.certificates.create_type.execute(
            {"code": "exam1", "name": name, "standard": True, "category": "academic"}
        )
        olympiad = await container.certificates.create_type.execute(
            {"code": "olymp1", "name": name, "category": "olympiad"}
        )
        await container.certificates.create_entry.execute(student, exam.id, {})
        medal = await container.certificates.create_entry.execute(
            student, olympiad.id, {}
        )
        scores = (await client.get("/v1/admission/test-scores")).json()
        assert [e["type_code"] for e in scores["exams"]] == ["exam1"], scores
        sug = (await client.get("/v1/admission/me/honor-suggestions")).json()
        assert [s["entry_id"] for s in sug["suggested"]] == [str(medal.id)]
        assert sug["suggested"][0]["category"] == "olympiad"
        r = await client.post(f"/v1/admission/me/honor-suggestions/{medal.id}/dismiss")
        assert r.status_code == 204
        sug = (await client.get("/v1/admission/me/honor-suggestions")).json()
        assert sug["suggested"] == [] and len(sug["available"]) == 1
        first = sug["available"][0]
        created = await client.post(
            "/v1/admission/me/items",
            json={
                "kind": "honor",
                "title": first["title"],
                "category": first["category"],
                "certificate_entry_id": first["entry_id"],
            },
        )
        assert created.status_code == 201, created.text
        assert created.json()["certificate_entry_id"] == str(medal.id)
        sug = (await client.get("/v1/admission/me/honor-suggestions")).json()
        assert sug["available"] == []
