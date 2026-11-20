"""Daily practice: theme of the day, sealed entry, cached evaluation, quota."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_practice import EssayPracticeService
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ConsentRequiredError,
    EssayTooShortError,
)
from app.modules.admission.domain.essay_flow import PRACTICE_THEMES, theme_for
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.shared.base_error import RateLimitedError
from app.shared.clock import local_today
from tests.admission.unit.fakes_flow import MemPractice
from tests.admission.unit.test_essays import Desk

import pytest

TEXT = "The kitchen smelled of cardamom and old tea. " * 5


def _reply(**kw: Any) -> dict[str, Any]:
    return {
        "summary": "Warm and concrete.",
        "scores": [
            {"key": k, "score": 3, "comment": "ok"}
            for k in ("imagery", "voice", "structure", "originality")
        ],
        "praise": ["the cardamom"],
        "try_next": ["find the turn"],
        "idea_seeds": ["the tea"],
        **kw,
    }


class Hits:
    def __init__(self, cap: int) -> None:
        self.count = 0
        self.cap = cap

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.count += 1
        if self.count > limit:
            raise RateLimitedError(params={"retry_after": 1})
        return self.count


class Bench(Desk):
    def __init__(self, *replies: dict[str, Any], consent: bool = True) -> None:
        super().__init__(*replies, consent=consent)
        self.practice = MemPractice()
        self.hits = Hits(1)
        inner = self.repo

        def uow() -> Any:
            from tests.admission.unit.test_items_service import ItemsUow

            u = ItemsUow(self.w.store, self.w.data)
            u.essays = inner  # type: ignore[attr-defined]
            u.practice = self.practice  # type: ignore[attr-defined]
            return u

        async def limit(_: UUID) -> int | None:
            return 1

        self.service = EssayPracticeService(
            uow,
            FlowGate(self.w.policy, self.consents),
            self.w.ai,
            self.clock,
            self.hits,  # type: ignore[arg-type]
            limit,
            BuiltinPrompts(),
        )


async def test_today_has_the_theme_of_the_local_day() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    t = await b.service.today(ctx)
    day = local_today(b.clock)
    assert t.day == day and t.theme == theme_for(day)
    assert t.prompt == PRACTICE_THEMES[t.theme] and t.entry is None


async def test_save_then_read_back_and_history() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    await b.service.save(ctx, "first")
    t = await b.service.save(ctx, TEXT)
    assert t.entry is not None and t.entry.body == TEXT
    assert (await b.service.today(ctx)).entry == t.entry
    assert [e.body for e in await b.service.history(ctx)] == [TEXT]


async def test_evaluate_caches_until_text_changes() -> None:
    b = Bench(_reply(), _reply(summary="Again."))
    ctx = await b.w.ctx()
    await b.service.save(ctx, TEXT)
    first = await b.service.evaluate(ctx, "en")
    assert first.entry is not None and first.entry.evaluation is not None
    assert [s.key for s in first.entry.evaluation.scores] == [
        "imagery",
        "voice",
        "structure",
        "originality",
    ]
    assert b.w.ai.calls[0]["task"].value == "admit_essay_practice"
    again = await b.service.evaluate(ctx, "en")
    assert len(b.w.ai.calls) == 1 and b.hits.count == 1
    assert again.entry == first.entry
    same = await b.service.save(ctx, TEXT)
    assert same.entry is not None and same.entry.evaluation is not None
    edited = await b.service.save(ctx, TEXT + " More.")
    assert edited.entry is not None and edited.entry.evaluation is None
    with pytest.raises(RateLimitedError):
        await b.service.evaluate(ctx, "en")


async def test_evaluate_gates() -> None:
    b = Bench(_reply(), consent=False)
    ctx = await b.w.ctx()
    await b.service.save(ctx, TEXT)
    with pytest.raises(ConsentRequiredError):
        await b.service.evaluate(ctx, "en")
    c = Bench(_reply())
    ctx = await c.w.ctx()
    with pytest.raises(EssayTooShortError):
        await c.service.evaluate(ctx, "en")
    await c.service.save(ctx, "too short")
    with pytest.raises(EssayTooShortError):
        await c.service.evaluate(ctx, "en")
    assert c.w.ai.calls == []


async def test_only_the_student_writes() -> None:
    b = Bench()
    staff = await b.staff("all", None)
    with pytest.raises(AdmissionForbiddenError):
        await b.service.save(staff, TEXT)


async def test_garbled_reply_is_normalised() -> None:
    b = Bench(_reply(scores=[{"key": "voice", "score": 99, "comment": "x"}]))
    ctx = await b.w.ctx()
    await b.service.save(ctx, TEXT)
    t = await b.service.evaluate(ctx, "en")
    assert t.entry is not None and t.entry.evaluation is not None
    got = {s.key: s.score for s in t.entry.evaluation.scores}
    assert got == {"imagery": 0, "voice": 5, "structure": 0, "originality": 0}
