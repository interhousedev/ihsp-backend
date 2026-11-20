"""AI usage analytics over HTTP on the real SQL reader (admin only)."""

from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import get_actor
from app.interfaces.http.v1.admin_ai.analytics import router as analytics_router
from app.modules.ai.application.ai_analytics import AiAnalytics
from app.modules.ai.domain.prompt_registry import PromptSlot
from app.modules.ai.infrastructure.analytics_reader import SqlAiAnalyticsReader
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
from app.shared.actor import Actor, Role
from app.shared.ids import new_id
from tests.conftest import HttpClientFactory
from tests.fakes.clock import FixedClock

import pytest
from fastapi import APIRouter
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

PREFIX = "/v1/admin/ai"
ADMIN = Actor(user_id=new_id(), roles=frozenset({Role.ADMIN}))
TEACHER = Actor(user_id=new_id(), roles=frozenset({Role.TEACHER}))
SLOT = PromptSlot("studio_quiz", "main", "Quiz", "x" * 400)


class FakeIdentity:
    async def get_users(self, ids: list[Any]) -> dict[Any, Any]:
        return {}


class FakeAdmin:
    async def versions(self, actor: Actor, task: str, name: str) -> list[Any]:
        return []


async def _client(
    http_client: HttpClientFactory,
    sessionmaker: async_sessionmaker[AsyncSession],
    clock: FixedClock,
    actor: Actor,
) -> AsyncClient:
    parent = APIRouter(prefix=PREFIX)
    parent.include_router(analytics_router)
    analytics = AiAnalytics(
        reader=SqlAiAnalyticsReader(sessionmaker),
        identity=FakeIdentity(),  # type: ignore[arg-type]
        clock=clock,
    )
    prompts = SimpleNamespace(
        registry=SimpleNamespace(
            slots=lambda task=None: [
                s for s in [SLOT] if task is None or s.task == task
            ]
        ),
        admin=FakeAdmin(),
    )
    return await http_client(
        [parent],
        overrides={get_actor: lambda: actor},
        ai=SimpleNamespace(analytics=analytics, prompts=prompts),
    )


async def _seed(sessionmaker: async_sessionmaker[AsyncSession]) -> None:
    async with sessionmaker() as session:
        for i, cost in enumerate((100, 300)):
            session.add(
                UsageEventRow(
                    occurred_at=datetime(2026, 10, 5, 8, i, tzinfo=UTC),
                    role="student",
                    task="studio_quiz",
                    feature="studio",
                    model="m",
                    cost_micro=cost,
                    success=True,
                    request_id="notebooks.studio_quiz.main",
                    pipeline="studio",
                    prompt_chars=400,
                    prompt_tokens_est=100,
                    answer_chars=50,
                    tool_calls=0,
                )
            )
        await session.commit()


@pytest.fixture
async def client(
    http_client: HttpClientFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
) -> AsyncClient:
    await _seed(sessionmaker_in_tx)
    return await _client(http_client, sessionmaker_in_tx, clock, ADMIN)


async def test_request_stats_group_by_request(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/analytics/requests")

    assert response.status_code == 200
    body = response.json()
    [item] = body["items"]
    assert item["key"] == "notebooks.studio_quiz.main"
    assert (item["calls"], item["cost_micro"]) == (2, 400)
    assert body["totals"]["calls"] == 2


async def test_spend_by_day(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/analytics/spend", params={"by": "day"})

    assert response.status_code == 200
    body = response.json()
    assert body["total_cost_micro"] == 400
    assert body["items"][0]["key"] == "2026-10-05"


async def test_spend_daily_matrix(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/analytics/spend/daily")

    assert response.status_code == 200
    [row] = response.json()["items"]
    assert row["request_id"] == "notebooks.studio_quiz.main"


async def test_a_huge_range_is_422(client: AsyncClient) -> None:
    response = await client.get(
        f"{PREFIX}/analytics/spend", params={"start": "2020-01-01", "end": "2026-10-06"}
    )

    assert response.status_code == 422


async def test_prompt_sizes_include_the_built_in(client: AsyncClient) -> None:
    response = await client.get(f"{PREFIX}/analytics/prompt-sizes")

    assert response.status_code == 200
    [item] = response.json()["items"]
    assert (item["task"], item["name"], item["version"]) == ("studio_quiz", "main", 0)
    assert (item["source"], item["chars"], item["tokens_est"]) == ("code", 400, 100)


async def test_teachers_are_refused(
    http_client: HttpClientFactory,
    sessionmaker_in_tx: async_sessionmaker[AsyncSession],
    clock: FixedClock,
) -> None:
    client = await _client(http_client, sessionmaker_in_tx, clock, TEACHER)

    response = await client.get(f"{PREFIX}/analytics/requests")

    assert response.status_code == 403
