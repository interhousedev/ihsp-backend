"""Catalog personal token over real HTTP: a counselor's agent proposes, never reviews.

ADM-INTL-3: the token reads the catalog, files a proposal and is refused everywhere
else (review, student data, /v1/me); a student cannot issue one.
"""

from collections.abc import AsyncIterator
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.modules.admission.infrastructure.orm._common import SCHEMA
from app.modules.identity.application.request_context import RequestContext
from app.modules.identity.domain.errors import PersonalTokenInvalidError
from app.modules.identity.domain.user import User
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.contracts.legal import LegalItem
from app.shared.ids import new_id
from tests.integration.conftest import ContainerFactory, IntegrationWorld

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

CTX = RequestContext(ip="203.0.113.7", user_agent="pytest")
TEXT = {"uz": "Matn", "ru": "Текст", "en": "Text"}


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


async def _user(container: Container, login: str, roles: set[Role]) -> Actor:
    auth = container.identity.auth
    user = User(
        id=new_id(),
        first_name="Agent",
        last_name="Owner",
        login=login,
        password_hash=await auth.hasher.hash("Secret-Passw0rd!"),
        roles=roles,
        recovery_email=f"{login}@example.org",
        recovery_email_verified_at=container.clock.now(),
        status=UserStatus.ACTIVE,
        preferences={"locale": "ru"},
    )
    async with auth.uow_factory() as uow:
        await uow.users.add(user)
        await uow.commit()
    return Actor(user_id=user.id, roles=frozenset(roles))


async def _consent(container: Container, actor: Actor) -> None:
    """Publish the global and admission privacy notices and accept both."""
    legal = container.legal
    for scope in ("global", "admission"):
        await legal.save_draft.execute(
            "privacy",
            title=TEXT,
            body_markdown=TEXT,
            announcement=None,
            app_scope=scope,
        )
        doc = await legal.publish.execute(
            "privacy", actor_id=actor.user_id, app_scope=scope
        )
        await legal.accept.execute(
            actor.user_id,
            [LegalItem(kind="privacy", version=doc.version, app_scope=scope)],
            ip=None,
            user_agent=None,
            app=scope,
            roles=[role.value for role in actor.roles],
            guardian_attested=True,
        )


async def _catalog_token(
    container: Container, world: IntegrationWorld, actor: Actor
) -> str:
    auth = container.identity.auth
    await auth.step_up.execute(actor, CTX)
    created = await auth.create_personal_token.execute(
        actor,
        name="catalog agent",
        scopes=["admission:catalog"],
        expires_in_days=90,
        otp_code=world.email.last_code,
        ctx=CTX,
    )
    return created.secret


async def test_catalog_token_proposes_but_cannot_review_or_read_students(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ADM-INTL-3: list, fact-spec, propose 201; review, students, /v1/me/* 403."""
    container = await make_container("all")
    counselor = await _user(container, "counselor.agent", {Role.COUNSELOR})
    await _consent(container, counselor)
    secret = await _catalog_token(container, world, counselor)
    app = build_http_app(container, process="all")
    auth = {"Authorization": f"Bearer {secret}"}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test", headers=auth
    ) as client:
        listed = await client.get("/v1/admission/catalog/institutions")
        assert listed.status_code == 200, listed.text

        spec = await client.get("/v1/admission/staff/catalog/fact-spec")
        assert spec.status_code == 200, spec.text

        proposed = await client.post(
            "/v1/admission/staff/catalog/proposals",
            json={
                "kind": "institution",
                "fields": {"name": "Agent University", "country": "US"},
                "source_url": "https://agent.example.edu/about",
            },
        )
        assert proposed.status_code == 201, proposed.text
        proposal_id = UUID(proposed.json()["id"])

        mine = await client.get("/v1/admission/staff/catalog/proposals")
        assert mine.status_code == 200, mine.text

        review = await client.post(
            f"/v1/admission/staff/catalog/proposals/{proposal_id}/review",
            json={"approve": True, "lock_version": 1},
        )
        assert review.status_code in (401, 403), review.text
        assert review.json()["type"] == "id/token-scope"

        students = await client.get(f"/v1/admission/students/{new_id()}/list")
        assert students.status_code == 403, students.text
        assert students.json()["type"] == "id/token-scope"

        me = await client.get("/v1/me/dashboard")
        assert me.status_code == 403, me.text
        assert me.json()["type"] == "id/token-scope"


async def test_student_cannot_issue_a_catalog_token(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    """ADM-INTL-3: a student-only account is refused the catalog scope."""
    container = await make_container("all")
    student = await _user(container, "student.agent", {Role.STUDENT})

    with pytest.raises(PersonalTokenInvalidError) as caught:
        await _catalog_token(container, world, student)

    assert caught.value.params["fields"] == ["scopes"]


_ID = "0191d7a2-1b2c-7d3e-8f40-123456789abc"
_STAFF = "/v1/admission/staff/catalog"
_REFUSED = [
    ("PATCH", f"{_STAFF}/institutions/{_ID}", {"logo_url": "https://x.example/l.png"}),
    (
        "PUT",
        f"{_STAFF}/institutions/{_ID}/supp-prompts/2026-27",
        {"prompts": []},
    ),
    ("POST", "/v1/id/personal-tokens", {"name": "x", "scopes": ["me:read"]}),
    ("POST", f"{_STAFF}/proposals/{_ID}/review", {"approve": True, "lock_version": 1}),
    ("GET", "/v1/id/me", None),
]
# Not matched by the allowlist, so refused before (or instead of) the handler.
_NEVER_SERVED = [
    ("GET", f"{_STAFF}/fact-spec/"),
    ("POST", f"{_STAFF}/proposals/"),
    ("HEAD", f"{_STAFF}/fact-spec"),
    ("OPTIONS", f"{_STAFF}/fact-spec"),
]


@pytest.mark.parametrize(("method", "path", "body"), _REFUSED)
async def test_catalog_token_is_refused_outside_the_allowlist_over_http(
    make_container: ContainerFactory,
    world: IntegrationWorld,
    method: str,
    path: str,
    body: dict[str, object] | None,
) -> None:
    """ADM-INTL-SEC-5: write, token-minting and identity routes answer 403."""
    container = await make_container("all")
    counselor = await _user(container, "counselor.gate", {Role.COUNSELOR})
    await _consent(container, counselor)
    secret = await _catalog_token(container, world, counselor)
    app = build_http_app(container, process="all")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {secret}"},
    ) as client:
        response = await client.request(method, path, json=body)

    assert response.status_code == 403, response.text
    assert response.json()["type"] == "id/token-scope"


@pytest.mark.parametrize(("method", "path"), _NEVER_SERVED)
async def test_catalog_token_never_reaches_slash_head_options_variants(
    make_container: ContainerFactory,
    world: IntegrationWorld,
    method: str,
    path: str,
) -> None:
    """ADM-INTL-SEC-6: trailing slash, HEAD and OPTIONS never succeed with the token.

    The gate matches the exact path and method, so it answers 403; the router may
    answer first (307/405). Any 2xx would be a bypass.
    """
    container = await make_container("all")
    counselor = await _user(container, "counselor.variant", {Role.COUNSELOR})
    await _consent(container, counselor)
    secret = await _catalog_token(container, world, counselor)
    app = build_http_app(container, process="all")

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {secret}"},
    ) as client:
        response = await client.request(method, path, json=None)

    assert response.status_code in (307, 403, 404, 405), response.status_code
    if response.status_code == 403:
        assert response.json()["type"] == "id/token-scope"
