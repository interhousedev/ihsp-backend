"""A limit set to -1 is no cap in every pool: AI tokens, smart weekly, web search.

The multiplier of an extension keeps -1 as -1. The fixed clock is 2026-10-06 09:00 UTC.
"""

from collections.abc import Callable
from datetime import date
from uuid import uuid4

from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.domain.assistant import Assistant
from app.modules.notebooks.application.budget import NotebookBudget
from app.settings import LimitsSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.limits import EffectiveLimits, LimitExtension, LimitSnapshot
from tests.fakes.ai.llm import ScriptedLlm
from tests.fakes.ai.stores import InMemoryBudgetStore, InMemorySearchQuotaStore
from tests.fakes.ai.web_search import ScriptedWebSearch
from tests.fakes.clock import FixedClock

TODAY = date(2026, 10, 6)
UNLIMITED_OVERRIDES = {
    "ai_session_tokens_student": -1,
    "ai_daily_tokens_student": -1,
    "ai_smart_requests_per_week_student": -1,
    "web_search_per_day_student": -1,
    "nb_daily_tokens_student": -1,
}


def limits_with(
    *,
    overrides: dict[str, int] | None = None,
    extensions: dict | None = None,
) -> EffectiveLimits:
    snapshot = LimitSnapshot(overrides=overrides or {}, extensions=extensions or {})

    async def load() -> LimitSnapshot:
        return snapshot

    async def roles_of(_user_id: object) -> frozenset[Role]:
        return frozenset({Role.STUDENT})

    return EffectiveLimits(LimitsSettings(), load, today=lambda: TODAY, roles=roles_of)


async def test_minus_one_is_no_cap_for_the_assistant_session_and_day_tokens(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    budget = BudgetService(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(overrides=UNLIMITED_OVERRIDES),
    )

    info = await budget.usage(user, Assistant.STUDENT)
    assert (info.session.limit, info.day.limit) == (None, None)

    await budget.add(user, 10**9)
    assert await budget.check(user, Assistant.STUDENT, 10**9) is None


async def test_minus_one_is_no_weekly_smart_cap_and_reservations_pass(
    settings: Settings, clock: FixedClock, make_actor: Callable[..., Actor]
) -> None:
    student = make_actor(Role.STUDENT, user_id=uuid4())
    budget = BudgetService(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(overrides=UNLIMITED_OVERRIDES),
    )

    limit = await budget.smart_limit(student)
    assert limit is None
    for _ in range(5):
        assert await budget.reserve_smart(student.user_id, limit) is None


async def test_minus_one_is_no_web_search_cap(
    settings: Settings, clock: FixedClock, make_actor: Callable[..., Actor]
) -> None:
    student = make_actor(Role.STUDENT, user_id=uuid4())
    service = WebSearchService(
        store=InMemorySearchQuotaStore(),
        gateway=ScriptedWebSearch(),
        llm=ScriptedLlm(),
        clock=clock,
        settings=settings,
        limits=limits_with(overrides=UNLIMITED_OVERRIDES),
    )

    assert (await service.quota(student)).limit is None
    for _ in range(4):
        await service.search(student, query="school news", locale="ru")


async def test_minus_one_is_no_notebook_daily_cap(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    budget = NotebookBudget(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(
            overrides={"nb_daily_tokens_student": -1, "nb_session_tokens_student": -1}
        ),
    )

    assert (await budget.usage(user)).day.limit is None
    await budget.add(user, 10**9)
    assert await budget.check(user, 10**9) is None


async def test_an_extension_multiplier_keeps_minus_one(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    extension = {
        user: LimitExtension(
            multiplier=3, values={"ai_daily_tokens_student": 5_000_000}
        )
    }
    budget = BudgetService(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(
            overrides={"ai_daily_tokens_student": -1}, extensions=extension
        ),
    )

    assert (await budget.usage(user, Assistant.STUDENT)).day.limit is None
