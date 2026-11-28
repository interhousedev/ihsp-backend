"""Catalog push token over real HTTP and Postgres.

A `admission:catalog-write` token upserts countries and institutions; a second
push reports unchanged, a verified country is skipped, a proposal token and a
revoked token are refused.
"""

import json
from collections.abc import AsyncIterator
from typing import Any

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.modules.admission.infrastructure.catalog_data import load_seed
from app.modules.admission.infrastructure.country_facts_loader import SEED_FILE
from app.modules.admission.infrastructure.orm._common import SCHEMA
from app.shared.actor import Actor, Role
from tests.integration.conftest import ContainerFactory, IntegrationWorld
from tests.integration.test_catalog_token_end_to_end import CTX, _consent, _user

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

_PUSH = "/v1/admission/staff/catalog/push"
# A real seed entry without media, so the test never fetches an image.
_INSTITUTION: dict[str, Any] = {
    k: v for k, v in load_seed()[0].items() if k not in ("logo_url", "cover_url")
}


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


async def _token(
    container: Container, world: IntegrationWorld, actor: Actor, scope: str
) -> tuple[str, Any]:
    auth = container.identity.auth
    await auth.step_up.execute(actor, CTX)
    created = await auth.create_personal_token.execute(
        actor,
        name=scope,
        scopes=[scope],
        expires_in_days=30,
        otp_code=world.email.last_code,
        ctx=CTX,
    )
    return created.secret, created


def _country() -> dict[str, Any]:
    data = json.loads(SEED_FILE.read_text(encoding="utf-8"))
    items = data["countries"] if isinstance(data, dict) else data
    first = items[0]
    return {
        "country": first["country"],
        "as_of": first["as_of"],
        "facts": first["facts"],
    }


def _statuses(response: Any) -> list[str]:
    assert response.status_code == 200, response.text
    return [r["status"] for r in response.json()["items"]]


async def test_write_token_pushes_idempotently_and_skips_verified(
    make_container: ContainerFactory, world: IntegrationWorld, engine: AsyncEngine
) -> None:
    container = await make_container("all")
    admin = await _user(container, "push.admin", {Role.ADMIN})
    await _consent(container, admin)
    secret, _ = await _token(container, world, admin, "admission:catalog-write")
    app = build_http_app(container, process="all")
    country = _country()

    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {secret}"},
    ) as client:
        first = await client.post(f"{_PUSH}/countries", json={"items": [country]})
        assert _statuses(first) == ["created"]
        again = await client.post(f"{_PUSH}/countries", json={"items": [country]})
        assert _statuses(again) == ["unchanged"]

        inst = await client.post(
            f"{_PUSH}/institutions", json={"items": [_INSTITUTION]}
        )
        assert _statuses(inst) == ["created"]
        inst_again = await client.post(
            f"{_PUSH}/institutions", json={"items": [_INSTITUTION]}
        )
        assert _statuses(inst_again) == ["unchanged"]

        bad = await client.post(
            f"{_PUSH}/institutions",
            json={"items": [{**_INSTITUTION, "logo_url": "http://x.example/l.png"}]},
        )
        assert _statuses(bad) == ["invalid"]
        assert bad.json()["items"][0]["field"] == "logo_url"

        async with engine.begin() as conn:
            await conn.execute(
                text(f"UPDATE {SCHEMA}.country_facts SET status = 'verified'")
            )
        changed = {**country, "as_of": "2020-01"}
        skipped = await client.post(f"{_PUSH}/countries", json={"items": [changed]})
        assert _statuses(skipped) == ["skipped"]

        reading = await client.get("/v1/admission/catalog/institutions")
        assert reading.status_code == 403, reading.text
        assert reading.json()["type"] == "id/token-scope"


async def test_propose_token_and_revoked_token_cannot_push(
    make_container: ContainerFactory, world: IntegrationWorld
) -> None:
    container = await make_container("all")
    admin = await _user(container, "push.admin2", {Role.ADMIN})
    await _consent(container, admin)
    counselor = await _user(container, "push.counselor", {Role.COUNSELOR})
    await _consent(container, counselor)
    propose, _ = await _token(container, world, counselor, "admission:catalog")
    write, created = await _token(container, world, admin, "admission:catalog-write")
    app = build_http_app(container, process="all")
    body = {"items": [_country()]}

    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        wrong = await client.post(
            f"{_PUSH}/countries",
            json=body,
            headers={"Authorization": f"Bearer {propose}"},
        )
        assert wrong.status_code == 403, wrong.text
        assert wrong.json()["type"] == "id/token-scope"

        await container.identity.auth.revoke_personal_token.execute(
            admin, created.token.id, CTX
        )
        revoked = await client.post(
            f"{_PUSH}/countries",
            json=body,
            headers={"Authorization": f"Bearer {write}"},
        )
        assert revoked.status_code == 401, revoked.text
