"""Deep read: paragraph reading, sealed cache, gates; group critique per target."""

from typing import Any

from app.modules.admission.application.essay_deep_read import EssayDeepReadService
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    ConsentRequiredError,
    EssayTooShortError,
)
from app.modules.admission.domain.essay_flow import PromptTarget
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.shared.base_error import RateLimitedError
from tests.admission.unit.test_essay_reviews import BODY, Bench, _base, _uni
from tests.admission.unit.test_items_service import OTHER

import pytest


def _deep(**kw: Any) -> dict[str, Any]:
    return {
        "paragraphs": [
            {
                "paragraph": 1,
                "role": "hook",
                "reveals": "curiosity",
                "strength": "strong",
            },
            {"paragraph": 2, "role": "close", "reveals": "service", "strength": "ok"},
            {"paragraph": 9, "role": "turn", "reveals": "ghost", "strength": "weak"},
        ],
        "uniqueness": 140,
        "uniqueness_note": "Distinct.",
        "tropes": ["the broken radio"],
        "moments": [
            {"paragraph": 1, "quote": "I fixed the old radio", "kind": "earned"},
            {"paragraph": 1, "quote": "invented line", "kind": "fresh"},
        ],
        "fix_paragraph": 7,
        "fix_dimension": "voice",
        "fix_problem": "Too brief.",
        "fix_try": "Add a scene.",
        **kw,
    }


class Deep(Bench):
    def __init__(
        self, *replies: dict[str, Any], quota: int = 10, consent: bool = True
    ) -> None:
        super().__init__(*replies, quota=quota, consent=consent)

        async def limit(_: Any) -> int | None:
            return quota

        self.deep = EssayDeepReadService(
            self.reviewer._uow,
            FlowGate(self.w.policy, self.consents),
            self.w.ai,
            self.clock,
            self.hits,  # type: ignore[arg-type]
            limit,
            BuiltinPrompts(),
            self.cipher,
            self.reviewer,
        )


async def test_deep_read_is_clamped_cached_and_counted_once() -> None:
    d = Deep(_deep())
    ctx, e = await d.essay()
    r = await d.deep.run(ctx, e.id, refresh=False, locale="en")
    assert not r.cached and not r.stale
    assert [p.paragraph for p in r.read.paragraphs] == [1, 2]
    assert r.read.uniqueness == 100 and r.read.fix_paragraph == 2
    assert [m.quote for m in r.read.moments] == ["I fixed the old radio"]
    assert d.w.ai.calls[0]["task"].value == "admit_essay_deep_read"
    again = await d.deep.run(ctx, e.id, refresh=False, locale="en")
    assert again.cached and again.read == r.read
    assert len(d.w.ai.calls) == 1 and d.hits.count == 1
    got = await d.deep.get(ctx, e.id, "en")
    assert got is not None and got.cached and not got.stale


async def test_deep_read_goes_stale_when_the_essay_changes() -> None:
    d = Deep(_deep())
    ctx, e = await d.essay()
    assert await d.deep.get(ctx, e.id, "en") is None
    await d.deep.run(ctx, e.id, refresh=False, locale="en")
    await d.svc.save(ctx, e.id, 1, {"body": BODY + " extra"})
    got = await d.deep.get(ctx, e.id, "en")
    assert got is not None and got.stale
    assert len(d.w.ai.calls) == 1


async def test_deep_read_gates() -> None:
    d = Deep(_deep(), quota=1)
    ctx, e = await d.essay(" ".join(["w"] * 10))
    with pytest.raises(EssayTooShortError):
        await d.deep.run(ctx, e.id, refresh=False, locale="en")
    await d.svc.save(ctx, e.id, 1, {"body": BODY})
    await d.deep.run(ctx, e.id, refresh=False, locale="en")
    with pytest.raises(RateLimitedError):
        await d.deep.run(ctx, e.id, refresh=True, locale="en")


async def test_deep_read_needs_ai_consent_and_ownership() -> None:
    d = Deep(_deep(), consent=False)
    ctx, e = await d.essay()
    with pytest.raises(ConsentRequiredError):
        await d.deep.run(ctx, e.id, refresh=False, locale="en")
    assert d.w.ai.calls == []
    ok = Deep(_deep())
    octx, _ = await ok.essay()
    with pytest.raises(AdmissionNotFoundError):
        await ok.deep.run(octx, OTHER, refresh=False, locale="en")


async def test_group_critique_reviews_each_target_under_its_prompt() -> None:
    d = Deep(_base(), _uni(), _uni())
    ctx, e = await d.essay()
    a, z = d.inst("A"), d.inst("Z")
    await d.svc.save(
        ctx,
        e.id,
        1,
        {
            "targets": [
                PromptTarget(a, 1, "Why A?", 250),
                PromptTarget(z, 1, "Why Z?", 100),
                PromptTarget(None, 1, "Common", 650),
            ]
        },
    )
    r = await d.deep.group_critique(ctx, e.id, refresh=False, locale="en")
    assert {u.institution_id for u in r.universities} == {a, z}
    users = [c["user"] for c in d.w.ai.calls if c["task"].value.endswith("uni_review")]
    assert any("Why A?" in u and "Word limit: 250" in u for u in users)
    assert any("Why Z?" in u and "Word limit: 100" in u for u in users)
    again = await d.deep.group_critique(ctx, e.id, refresh=False, locale="en")
    assert all(u.cached for u in again.universities) and len(d.w.ai.calls) == 3
    got = await d.reviewer.get(ctx, e.id, "en")
    assert not any(u.stale for u in got.universities)
