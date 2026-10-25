"""Limits, usage report and extensions over HTTP (Administration only)."""

from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_ai import router
from app.modules.ai.application.usage_report import UsageReport
from app.modules.ai.infrastructure.usage_reader import SqlUsageReader
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.admin.conftest import Stack
from tests.conftest import HttpClientFactory
from tests.factories.notify import make_user
from tests.fakes.clock import FixedClock

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker


@pytest.fixture
async def client(
    stack: Stack,
    clock: FixedClock,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    http_client: HttpClientFactory,
) -> AsyncClient:
    report = UsageReport(
        reader=SqlUsageReader(sessionmaker_in_tx), identity=stack.identity, clock=clock
    )
    return await http_client(
        [router],
        overrides={get_actor: lambda: stack.actor},
        admin=stack.admin,
        ai=SimpleNamespace(usage_report=report),
    )


async def test_the_limits_come_grouped_with_their_value_and_default(
    client: AsyncClient,
) -> None:
    response = await client.get("/v1/admin/ai/limits")

    assert response.status_code == 200
    rows = {row["key"]: row for row in response.json()["limits"]}
    daily = rows["ai_daily_tokens_student"]
    assert daily["group"] == "assistant"
    assert daily["unit"] == "tokens"
    assert daily["period"] == "day"
    assert daily["label_key"] == "admin-limit-ai-daily-tokens-student"
    assert (daily["value"], daily["default"], daily["overridden"]) == (
        600000,
        600000,
        False,
    )
    assert "lms_ai_session_tokens" not in rows


async def test_a_put_changes_a_limit_and_bad_input_is_refused(
    client: AsyncClient,
) -> None:
    response = await client.put(
        "/v1/admin/ai/limits", json={"limits": {"nb_chat_per_minute": 25}}
    )

    assert response.status_code == 200
    row = next(r for r in response.json()["limits"] if r["key"] == "nb_chat_per_minute")
    assert (row["value"], row["overridden"]) == (25, True)

    unknown = await client.put(
        "/v1/admin/ai/limits", json={"limits": {"not_a_limit": 1}}
    )
    assert unknown.status_code == 422
    wrong_type = await client.put(
        "/v1/admin/ai/limits", json={"limits": {"nb_chat_per_minute": "lots"}}
    )
    assert wrong_type.status_code == 422


async def test_students_cannot_read_or_change_the_limits(
    stack: Stack, http_client: HttpClientFactory
) -> None:
    student = Actor(user_id=new_id(), roles=frozenset({Role.STUDENT}))
    client = await http_client(
        [router], overrides={get_actor: lambda: student}, admin=stack.admin
    )

    assert (await client.get("/v1/admin/ai/limits")).status_code == 403
    assert (
        await client.put(
            "/v1/admin/ai/limits", json={"limits": {"nb_chat_per_minute": 1}}
        )
    ).status_code == 403
    assert (await client.get("/v1/admin/ai/usage")).status_code == 403


async def test_an_extension_is_created_listed_found_and_removed(
    client: AsyncClient, stack: Stack
) -> None:
    student_id = new_id()
    stack.identity.add_user(
        make_user(
            Role.STUDENT, first_name="Aziza", last_name="Karimova", user_id=student_id
        ),
        901,
    )

    found = await client.get(
        "/v1/admin/ai/limit-extensions/students", params={"q": "Azi"}
    )
    assert [item["name"] for item in found.json()["items"]] == ["Aziza Karimova"]

    saved = await client.put(
        f"/v1/admin/ai/limit-extensions/{student_id}",
        json={"multiplier": 3, "note": "thesis", "expires_on": "2026-12-31"},
    )
    assert saved.status_code == 200
    body: dict[str, Any] = saved.json()
    assert (body["user_name"], body["multiplier"], body["active"]) == (
        "Aziza Karimova",
        3,
        True,
    )

    listed = await client.get(
        "/v1/admin/ai/limit-extensions", params={"user_id": str(student_id)}
    )
    assert len(listed.json()["items"]) == 1

    removed = await client.delete(f"/v1/admin/ai/limit-extensions/{student_id}")
    assert removed.status_code == 204
    assert (await client.get("/v1/admin/ai/limit-extensions")).json()["items"] == []


async def test_an_extension_without_a_grant_is_refused(
    client: AsyncClient, stack: Stack
) -> None:
    student_id = new_id()
    stack.identity.add_user(make_user(Role.STUDENT, user_id=student_id), 902)

    response = await client.put(
        f"/v1/admin/ai/limit-extensions/{student_id}", json={"note": "nothing"}
    )

    assert response.status_code == 422


async def test_the_usage_report_fills_every_day_of_the_range(
    client: AsyncClient,
) -> None:
    response = await client.get(
        "/v1/admin/ai/usage",
        params={"from": "2026-10-01", "to": "2026-10-06", "group_by": "day"},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["from"] == "2026-10-01"
    assert body["to"] == "2026-10-06"
    assert len(body["rows"]) == 6
    assert set(body) >= {
        "totals",
        "top_users",
        "month",
        "today",
        "rows",
        "generated_at",
    }
    assert body["month"]["days_in_month"] == 31


async def test_the_usage_range_is_limited(client: AsyncClient) -> None:
    response = await client.get(
        "/v1/admin/ai/usage", params={"from": "2024-01-01", "to": "2026-10-06"}
    )

    assert response.status_code == 422
