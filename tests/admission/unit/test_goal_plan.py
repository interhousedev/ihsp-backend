"""Goal plan: milestone CRUD, cap, lock, ownership and the config caps."""

import datetime as dt
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.admission.application.goal_plan import GoalPlanService
from app.modules.admission.application.goal_plan_suggest import GoalPlanSuggester
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    CharLimitError,
    ConsentRequiredError,
    ItemLimitError,
)
from app.modules.admission.domain.goal_plan import MAX_MILESTONES, GoalMilestone
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.ports.consent import AI
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeConsents
from tests.admission.unit.test_items_service import (
    OTHER,
    STUDENT,
    ItemsUow,
    World,
)
from tests.fakes.clock import FixedClock

import pytest


class MemGoals:
    """A GoalRepository over a dict."""

    def __init__(self, rows: dict[UUID, GoalMilestone]) -> None:
        self.rows = rows

    async def list_for(self, student_id: UUID) -> list[GoalMilestone]:
        found = [m for m in self.rows.values() if m.student_id == student_id]
        return sorted(found, key=lambda m: m.sort_order)

    async def get(self, milestone_id: UUID) -> GoalMilestone | None:
        return self.rows.get(milestone_id)

    async def add(self, milestone: GoalMilestone) -> GoalMilestone:
        self.rows[milestone.id] = milestone
        return milestone

    async def update(self, milestone: GoalMilestone) -> GoalMilestone:
        stored = replace(milestone, lock_version=milestone.lock_version + 1)
        self.rows[milestone.id] = stored
        return stored

    async def delete(self, milestone_id: UUID) -> None:
        self.rows.pop(milestone_id, None)


def _plan() -> tuple[World, GoalPlanService]:
    w = World()
    rows: dict[UUID, GoalMilestone] = {}

    def uow() -> Any:
        u = ItemsUow(w.store, w.data)
        u.goals = MemGoals(rows)  # type: ignore[attr-defined]
        return u

    return w, GoalPlanService(uow, w.policy, FixedClock(NOW))


def _draft(title: str = "Reach 1400 SAT", **kw: Any) -> GoalMilestone:
    return GoalMilestone(new_id(), STUDENT, title, **kw)


async def test_create_normalizes_month_and_appends() -> None:
    w, svc = _plan()
    ctx = await w.ctx()
    a = await svc.create(ctx, _draft(due_month=dt.date(2027, 3, 17)))
    b = await svc.create(ctx, _draft("Second"))
    assert a.due_month == dt.date(2027, 3, 1)
    assert (a.sort_order, b.sort_order) == (0, 1)
    assert [m.id for m in await svc.list(ctx, STUDENT)] == [a.id, b.id]


async def test_cap_and_title_limit() -> None:
    w, svc = _plan()
    ctx = await w.ctx()
    with pytest.raises(CharLimitError):
        await svc.create(ctx, _draft("x" * 121))
    for _ in range(MAX_MILESTONES):
        await svc.create(ctx, _draft())
    with pytest.raises(ItemLimitError):
        await svc.create(ctx, _draft())


async def test_link_to_foreign_item_is_not_found() -> None:
    w, svc = _plan()
    mine = await w.item()
    ctx = await w.ctx()
    ok = await svc.create(ctx, _draft(item_id=mine.id))
    assert ok.item_id == mine.id
    with pytest.raises(AdmissionNotFoundError):
        await svc.create(ctx, _draft(item_id=new_id()))


async def test_update_status_lock_and_done_at() -> None:
    w, svc = _plan()
    ctx = await w.ctx()
    m = await svc.create(ctx, _draft())
    done = await svc.update(ctx, m.id, {"status": "done"}, m.lock_version)
    assert done.done_at == NOW and done.lock_version == 1
    with pytest.raises(AdmissionConflictError):
        await svc.update(ctx, m.id, {"title": "x"}, 0)
    back = await svc.update(ctx, m.id, {"status": "planned"}, 1)
    assert back.done_at is None
    with pytest.raises(AdmissionForbiddenError):
        await svc.update(ctx, m.id, {"source": "ai"}, 2)


async def test_other_student_cannot_touch_and_delete() -> None:
    w, svc = _plan()
    m = await svc.create(await w.ctx(), _draft())
    other = await w.ctx(OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await svc.delete(other, m.id)
    await svc.delete(await w.ctx(), m.id)
    assert await svc.list(await w.ctx(), STUDENT) == []


async def test_replace_keeps_known_ids_and_drops_the_rest() -> None:
    w, svc = _plan()
    ctx = await w.ctx()
    a = await svc.create(ctx, _draft("Keep"))
    await svc.create(ctx, _draft("Drop"))
    out = await svc.replace(
        ctx, [_draft("New", due_month=dt.date(2027, 5, 9)), replace(a, title="Kept")]
    )
    assert [m.title for m in out] == ["New", "Kept"]
    assert [m.sort_order for m in out] == [0, 1]
    assert out[0].due_month == dt.date(2027, 5, 1)
    assert out[1].id == a.id
    assert [m.title for m in await svc.list(ctx, STUDENT)] == ["New", "Kept"]


async def test_replace_rejects_more_than_twelve() -> None:
    w, svc = _plan()
    ctx = await w.ctx()
    with pytest.raises(ItemLimitError):
        await svc.replace(ctx, [_draft(f"m{i}") for i in range(MAX_MILESTONES + 1)])


class _Hits:
    def __init__(self) -> None:
        self.count = 0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.count += 1
        if self.count > limit:
            raise RateLimitedError(params={"retry_after": 1})
        return self.count


def _suggester(
    w: World, rows: dict[UUID, GoalMilestone], *, consent: bool = True, limit: int = 1
) -> GoalPlanSuggester:
    def uow() -> Any:
        u = ItemsUow(w.store, w.data)
        u.goals = MemGoals(rows)  # type: ignore[attr-defined]
        return u

    async def quota(_: UUID) -> int | None:
        return limit

    return GoalPlanSuggester(
        uow,
        w.policy,
        w.ai,
        FakeConsents({STUDENT: frozenset({AI} if consent else set())}),
        FixedClock(NOW),
        _Hits(),  # type: ignore[arg-type]
        quota,
        BuiltinPrompts(),
    )


async def test_suggest_cleans_proposals_and_needs_consent_and_quota() -> None:
    item_id = new_id()
    reply = {
        "suggestions": [
            {"title": "**Join** a contest", "item_id": str(item_id), "months_ahead": 3},
            {"title": "join a contest", "item_id": "", "months_ahead": 2},
            {"title": "Write essay", "item_id": str(new_id()), "months_ahead": 99},
        ]
    }
    w = World(reply, reply)
    svc = _suggester(w, {})
    ctx = await w.ctx()
    out = await svc.suggest(ctx, "en")
    assert [s.title for s in out] == ["Join a contest", "Write essay"]
    assert out[0].item_id is None and out[1].item_id is None
    assert out[0].due_month == dt.date(NOW.year, NOW.month, 1).replace(
        month=(NOW.month + 2) % 12 + 1, year=NOW.year + (NOW.month + 2) // 12
    )
    with pytest.raises(RateLimitedError):
        await svc.suggest(ctx, "en")
    with pytest.raises(ConsentRequiredError):
        await _suggester(w, {}, consent=False).suggest(ctx, "en")
