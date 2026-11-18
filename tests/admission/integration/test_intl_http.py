"""International catalog facts and the essay check over real HTTP and PostgreSQL."""

from collections.abc import AsyncIterator, Iterator
from typing import Any
from uuid import UUID

from app.bootstrap.container import Container
from app.bootstrap.http_app import build_http_app
from app.interfaces.http.dependencies import get_actor
from app.modules.admission.infrastructure.orm._common import SCHEMA
from app.modules.admission.infrastructure.orm.access import EntitlementRow
from app.modules.admission.ports.consent import AI
from app.modules.identity.domain.user import User
from app.modules.legal.infrastructure.purpose_consents import SqlPurposeConsents
from app.shared.actor import Actor, Role
from app.shared.contracts.identity import UserStatus
from app.shared.contracts.legal import LegalItem
from app.shared.ids import new_id
from tests.integration.conftest import ContainerFactory

import pytest
import pytest_asyncio
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

TEXT = {"uz": "Matn", "ru": "Текст", "en": "Text"}
URL = "https://example.edu/admissions"
FACT = {"value": 12.5, "source_url": URL, "year": 2025, "note": None}
PROPOSALS = "/v1/admission/staff/catalog/proposals"
FACT_SPEC = "/v1/admission/staff/catalog/fact-spec"
ESSAYS = "/v1/admission/essays"


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


async def _user(container: Container, login: str, role: Role) -> Actor:
    auth = container.identity.auth
    user = User(
        id=new_id(),
        first_name="Intl",
        last_name="Tester",
        login=login,
        password_hash=await auth.hasher.hash("Secret-Passw0rd!"),
        roles={role},
        recovery_email=f"{login}@example.org",
        recovery_email_verified_at=container.clock.now(),
        status=UserStatus.ACTIVE,
        preferences={"locale": "ru"},
    )
    async with auth.uow_factory() as uow:
        await uow.users.add(user)
        await uow.commit()
    actor = Actor(user_id=user.id, roles=frozenset({role}))
    await _consent(container, actor)
    return actor


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


class _As:
    """Switch the authenticated caller of the app under test."""

    def __init__(self, app: FastAPI, actor: Actor) -> None:
        self.app = app
        self.set(actor)

    def set(self, actor: Actor) -> None:
        """Act as `actor` from now on."""
        self.app.dependency_overrides[get_actor] = lambda: actor


@pytest.fixture
def overrides_cleaned() -> Iterator[list[FastAPI]]:
    """Drop the actor overrides of every app a test built."""
    apps: list[FastAPI] = []
    yield apps
    for app in apps:
        app.dependency_overrides.clear()


async def _http(
    make_container: ContainerFactory,
    cleaned: list[FastAPI],
    role: Role,
    login: str,
) -> tuple[Container, AsyncClient, _As, Actor]:
    container = await make_container("all")
    actor = await _user(container, login, role)
    app = build_http_app(container, process="all")
    cleaned.append(app)
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    return container, client, _As(app, actor), actor


async def _propose(client: AsyncClient, name: str, **extra: object) -> dict[str, Any]:
    body = {
        "kind": "institution",
        "fields": {"name": name, "country": "GB"},
        "source_url": URL,
    } | extra
    response = await client.post(PROPOSALS, json=body)
    return {"status": response.status_code, "json": response.json()}


async def test_fact_spec_is_localized_and_for_proposers_only(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-8: the registry is served in the request language to staff only."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.spec"
    )
    async with client:
        ru = await client.get(FACT_SPEC, headers={"Accept-Language": "ru"})
        en = await client.get(FACT_SPEC, headers={"Accept-Language": "en"})
        assert ru.status_code == 200, ru.text
        assert en.status_code == 200, en.text
        assert ru.json() != en.json()

        student = await _user(container, "intl.student.spec", Role.STUDENT)
        switch.set(student)
        denied = await client.get(FACT_SPEC)
        assert denied.status_code in (403, 404), denied.text


async def test_proposal_with_facts_is_stored_and_invalid_fact_is_422(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-1: facts come back apart from fields; a bad fact is refused."""
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.facts"
    )
    async with client:
        ok = await _propose(client, "Facts University", facts={"acceptance_rate": FACT})
        assert ok["status"] == 201, ok
        assert "facts" not in ok["json"]["fields"]
        assert ok["json"]["facts"]["acceptance_rate"]["year"] == 2025

        wrong_unit = await _propose(
            client,
            "Bad Unit University",
            facts={
                "intl_tuition_usd": {
                    "value": {"amount": 1, "currency": "GBP"},
                    "source_url": URL,
                    "year": 2025,
                    "note": None,
                }
            },
        )
        assert wrong_unit["status"] == 422, wrong_unit

        no_source = await _propose(
            client,
            "No Source University",
            facts={"acceptance_rate": {"value": 12.5, "year": 2025}},
        )
        assert no_source["status"] == 422, no_source


async def test_duplicate_institution_proposal_is_409(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-4: a pending create, then an approved one, block the same name."""
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.dup"
    )
    async with client:
        first = await _propose(client, "Duplicate University")
        assert first["status"] == 201, first

        pending = await _propose(client, "Duplicate University")
        assert pending["status"] == 409, pending  # ADM-INTL-5

        review = await client.post(
            f"{PROPOSALS}/{first['json']['id']}/review",
            json={"approve": True, "lock_version": first["json"]["lock_version"]},
        )
        assert review.status_code == 200, review.text

        approved = await _propose(client, "duplicate  university")
        assert approved["status"] == 409, approved


async def test_daily_proposal_limit_is_429(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-6: the proposal over the daily limit is refused with 429."""
    container, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.limit"
    )
    # The limit is read once at wiring; lower it for this container only.
    container.admission.catalog_proposals._per_day = 1
    async with client:
        first = await _propose(client, "Limit One University")
        assert first["status"] == 201, first
        second = await _propose(client, "Limit Two University")
        assert second["status"] == 429, second


async def test_approved_facts_show_in_the_details_view(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-10: an approved proposal's facts appear in `details`."""
    _, client, _, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.apply"
    )
    async with client:
        made = await _propose(
            client, "Details University", facts={"acceptance_rate": FACT}
        )
        assert made["status"] == 201, made
        review = await client.post(
            f"{PROPOSALS}/{made['json']['id']}/review",
            json={"approve": True, "lock_version": made["json"]["lock_version"]},
        )
        assert review.status_code == 200, review.text
        institution_id = review.json()["applied_id"]  # ADM-INTL-12

        detail = await client.get(
            f"/v1/admission/catalog/institutions/{institution_id}",
            headers={"Accept-Language": "en"},
        )
        assert detail.status_code == 200, detail.text
        rows = [r for g in detail.json()["details"] for r in g["rows"]]
        fact = next(r for r in rows if r["key"] == "acceptance_rate")
        assert fact["source_url"] == URL
        assert fact["year"] == 2025
        assert fact["value_text"]


async def _essay_student(
    container: Container, client: AsyncClient, switch: _As, login: str, body: str
) -> tuple[Actor, str]:
    student = await _user(container, login, Role.STUDENT)
    async with container.sessionmaker() as session, session.begin():
        session.add(
            EntitlementRow(
                user_id=student.user_id,
                kind="school_student",
                cohort_year=None,
                granted_by=None,
            )
        )
    await SqlPurposeConsents(container.sessionmaker).grant(
        student.user_id, AI, now=container.clock.now()
    )
    switch.set(student)
    created = await client.post(ESSAYS, json={"prompt_text": "Why this field?"})
    assert created.status_code in (200, 201), created.text
    essay = created.json()
    saved = await client.patch(
        f"{ESSAYS}/{essay['id']}",
        json={"lock_version": essay["lock_version"], "body": body},
    )
    assert saved.status_code == 200, saved.text
    return student, essay["id"]


async def test_essay_check_scores_a_draft_and_guards_short_and_foreign(
    make_container: ContainerFactory, overrides_cleaned: list[FastAPI]
) -> None:
    """ADM-INTL-4: check returns a score; short drafts 422, others' essays 404."""
    container, client, switch, _ = await _http(
        make_container, overrides_cleaned, Role.ADMIN, "intl.admin.essay"
    )
    long_body = " ".join(["word"] * 80)
    async with client:
        _, essay_id = await _essay_student(
            container, client, switch, "intl.student.essay", long_body
        )
        ok = await client.post(f"{ESSAYS}/{essay_id}/coach/check")
        assert ok.status_code == 200, ok.text
        assert {"score", "band", "dimensions"} <= ok.json().keys()

        _, short_id = await _essay_student(
            container, client, switch, "intl.student.short", "too short"
        )
        short = await client.post(f"{ESSAYS}/{short_id}/coach/check")
        assert short.status_code == 422, short.text

        other = await client.post(f"{ESSAYS}/{essay_id}/coach/check")
        assert other.status_code == 404, other.text
        assert UUID(essay_id)
