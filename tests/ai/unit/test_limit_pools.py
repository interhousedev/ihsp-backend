"""Each pool reads the effective limits: an override, an extension, staff unlimited.

One test per pool: the assistant budget (and its smart weekly limit), the notebook
budget and the web search quota. The fixed clock is 2026-10-06 09:00 UTC.
"""

from collections.abc import Callable
from datetime import date
from uuid import UUID, uuid4

from app.modules.ai.application.budget import BudgetService
from app.modules.ai.application.web_search import WebSearchService
from app.modules.ai.domain.assistant import Assistant
from app.modules.notebooks.application.budget import NotebookBudget
from app.settings import LimitsSettings, Settings
from app.shared.actor import Actor, Role
from app.shared.contracts.web_search import WebSearchQuotaError
from app.shared.limits import EffectiveLimits, LimitExtension, LimitSnapshot
from tests.fakes.ai.llm import ScriptedLlm
from tests.fakes.ai.stores import InMemoryBudgetStore, InMemorySearchQuotaStore
from tests.fakes.ai.web_search import ScriptedWebSearch
from tests.fakes.clock import FixedClock

import pytest

TODAY = date(2026, 10, 6)


def limits_with(
    *,
    overrides: dict[str, int] | None = None,
    extensions: dict[UUID, LimitExtension] | None = None,
    roles: dict[UUID, frozenset[Role]] | None = None,
    today: date = TODAY,
) -> EffectiveLimits:
    snapshot = LimitSnapshot(overrides=overrides or {}, extensions=extensions or {})

    async def load() -> LimitSnapshot:
        return snapshot

    async def roles_of(user_id: UUID) -> frozenset[Role]:
        return (roles or {}).get(user_id, frozenset({Role.STUDENT}))

    return EffectiveLimits(LimitsSettings(), load, today=lambda: today, roles=roles_of)


async def test_the_student_assistant_limits_come_from_the_override(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    limits = limits_with(
        overrides={"ai_session_tokens_student": 1000, "ai_daily_tokens_student": 5000}
    )
    budget = BudgetService(InMemoryBudgetStore(), clock, settings, limits=limits)

    info = await budget.usage(user, Assistant.STUDENT)
    assert (info.session.limit, info.day.limit) == (1000, 5000)

    await budget.add(user, 900)
    hit = await budget.check(user, Assistant.STUDENT, 200)
    assert hit is not None
    assert hit.scope == "session"


async def test_a_student_extension_raises_the_assistant_limit_until_it_expires(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    extension = {user: LimitExtension(multiplier=2, expires_on=date(2026, 10, 6))}

    active = BudgetService(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(extensions=extension, today=TODAY),
    )
    expired = BudgetService(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(extensions=extension, today=date(2026, 10, 7)),
    )

    base = LimitsSettings().ai_daily_tokens_student
    assert (await active.usage(user, Assistant.STUDENT)).day.limit == 2 * base
    assert (await expired.usage(user, Assistant.STUDENT)).day.limit == base


async def test_the_smart_weekly_limit_follows_the_override_and_the_extension(
    settings: Settings, clock: FixedClock, make_actor: Callable[..., Actor]
) -> None:
    student_id, teacher_id = uuid4(), uuid4()
    limits = limits_with(
        overrides={"ai_smart_requests_per_week_student": 2},
        extensions={student_id: LimitExtension(multiplier=3)},
        roles={teacher_id: frozenset({Role.TEACHER})},
    )
    budget = BudgetService(InMemoryBudgetStore(), clock, settings, limits=limits)

    assert await budget.smart_limit(make_actor(Role.STUDENT, user_id=student_id)) == 6
    assert (
        await budget.smart_limit(make_actor(Role.TEACHER, user_id=teacher_id)) is None
    )


async def test_the_staff_assistant_pool_has_no_token_cap(
    settings: Settings, clock: FixedClock
) -> None:
    lecturer = uuid4()
    budget = BudgetService(InMemoryBudgetStore(), clock, settings, limits=limits_with())

    info = await budget.usage(lecturer, Assistant.LMS_AUTHOR)

    assert info.session.limit is None
    assert info.day.limit is None


async def test_the_notebook_pool_reads_the_override_and_blocks_over_it(
    settings: Settings, clock: FixedClock
) -> None:
    user = uuid4()
    budget = NotebookBudget(
        InMemoryBudgetStore(),
        clock,
        settings,
        limits=limits_with(overrides={"nb_daily_tokens_student": 100}),
    )

    assert (await budget.usage(user)).day.limit == 100

    await budget.add(user, 90)
    hit = await budget.check(user, 20)
    assert hit is not None
    assert hit.scope == "day"


async def test_the_course_notebook_pool_is_unlimited(
    settings: Settings, clock: FixedClock
) -> None:
    budget = NotebookBudget(
        InMemoryBudgetStore(), clock, settings, for_course=True, limits=limits_with()
    )

    info = await budget.usage(uuid4())

    assert info.session.limit is None
    assert info.day.limit is None


async def test_the_web_search_quota_follows_the_override_and_staff_are_unlimited(
    settings: Settings, clock: FixedClock, make_actor: Callable[..., Actor]
) -> None:
    student_id, teacher_id = uuid4(), uuid4()
    limits = limits_with(
        overrides={"web_search_per_day_student": 2},
        roles={teacher_id: frozenset({Role.TEACHER})},
    )
    service = WebSearchService(
        store=InMemorySearchQuotaStore(),
        gateway=ScriptedWebSearch(),
        llm=ScriptedLlm(),
        clock=clock,
        settings=settings,
        limits=limits,
    )
    student = make_actor(Role.STUDENT, user_id=student_id)
    teacher = make_actor(Role.TEACHER, user_id=teacher_id)

    assert (await service.quota(student)).limit == 2
    await service.search(student, query="school news", locale="ru")
    await service.search(student, query="school news", locale="ru")
    with pytest.raises(WebSearchQuotaError):
        await service.search(student, query="school news", locale="ru")

    assert (await service.quota(teacher)).limit is None
    for _ in range(3):
        await service.search(teacher, query="school news", locale="ru")
