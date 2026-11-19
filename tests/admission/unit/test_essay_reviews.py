"""Essay reviews: one base call plus one per university, sealed cache, gates."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_reviews import EssayReviewService
from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    ConsentRequiredError,
    EssayTooShortError,
    ItemLimitError,
)
from app.modules.admission.domain.exemplars import Exemplar, ExemplarMatch
from app.modules.admission.infrastructure.ai.prompt_source import BuiltinPrompts
from app.modules.admission.infrastructure.ai.prompts import essay_review
from app.modules.admission.infrastructure.ai.prompts import essays as coach_prompts
from app.modules.admission.ports.consent import AI, STAFF_VIEW
from app.shared.base_error import RateLimitedError
from app.shared.contracts.ai import AiProviderError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW
from tests.admission.unit.fakes_reviews import FixedExemplars
from tests.admission.unit.test_essays import Desk, _Hits
from tests.admission.unit.test_items_service import OTHER, STUDENT

import pytest

BODY = (
    "I fixed the old radio in my grandmother's kitchen when I was twelve. "
    + "word " * 40
    + "\n\nLater I built a club that repairs phones for neighbours every Friday. "
    + "more " * 10
)


def _base(**kw: Any) -> dict[str, Any]:
    return {
        "dimensions": [
            {"dim": d, "score": 3, "quote": "I fixed the old radio", "comment": "ok"}
            for d in essay_review.DIMENSIONS
        ],
        "summary": "Solid start.",
        "strengths": ["voice"],
        "improvements": ["focus"],
        "paragraphs": [{"paragraph": 1, "note": "tighten"}],
        "patterns": [],
        **kw,
    }


def _uni(**kw: Any) -> dict[str, Any]:
    return {
        "alignment": 70,
        "goals": [
            {
                "key": "mission",
                "alignment": "strong",
                "evidence": "repairs phones for neighbours",
                "suggestion": "name the impact",
            }
        ],
        "fit_summary": "Fits service.",
        "supplement_tips": [],
        "risks": [],
        **kw,
    }


class Bench(Desk):
    def __init__(
        self, *replies: dict[str, Any], consent: bool = True, quota: int = 10
    ) -> None:
        super().__init__(*replies, consent=consent)
        self.exemplars = FixedExemplars(())
        self.hits = _Hits()

        def uow() -> Any:
            from tests.admission.unit.test_items_service import ItemsUow

            u = ItemsUow(self.w.store, self.w.data)
            u.essays = self.repo  # type: ignore[attr-defined]
            u.essay_reviews = self.reviews  # type: ignore[attr-defined]
            return u

        async def limit(_: UUID) -> int | None:
            return quota

        self.reviewer = EssayReviewService(
            uow,
            self.w.policy,
            self.w.ai,
            self.consents,
            self.clock,
            self.hits,  # type: ignore[arg-type]
            limit,
            limit,
            BuiltinPrompts(),
            self.exemplars,
            self.cipher,
        )

    def inst(self, name: str, sourced: bool = True) -> UUID:
        facts = (
            {"mission": FactView("Serve the community", "http://s/mission", 2025)}
            if sourced
            else {"mission": FactView("Serve the community")}
        )
        i = CatalogInstitution(
            new_id(), name.lower(), name, "US", None, "published", facts
        )
        self.w.store.institutions[i.id] = i
        return i.id

    async def essay(self, body: str = BODY) -> Any:
        ctx = await self.w.ctx()
        e = await self.svc.create(ctx, {"prompt_text": "Tell us about you"})
        await self.svc.save(ctx, e.id, 0, {"body": body})
        return ctx, e


async def test_two_universities_cost_three_calls_and_repeat_costs_none() -> None:
    """ADM-REV-1: 1 essay x 2 unis = 1 base + 2 uni calls; a repeat is cached."""
    b = Bench(_base(), _uni(), _uni())
    ctx, e = await b.essay()
    a, z = b.inst("A"), b.inst("Z")
    r = await b.reviewer.run(ctx, e.id, [a, z], refresh=False, locale="en")
    tasks = [c["task"].value for c in b.w.ai.calls]
    assert tasks == [
        "admit_essay_review",
        "admit_essay_uni_review",
        "admit_essay_uni_review",
    ]
    assert r.base is not None and not r.base_cached
    assert [u.cached for u in r.universities] == [False, False]
    assert b.hits.count == 3
    again = await b.reviewer.run(ctx, e.id, [a, z], refresh=False, locale="en")
    assert len(b.w.ai.calls) == 3 and b.hits.count == 3
    assert again.base_cached and all(u.cached for u in again.universities)
    assert again.base == r.base


async def test_refresh_calls_again_and_body_change_is_stale() -> None:
    """ADM-REV-2: refresh forces calls; a changed body marks stored reviews stale."""
    b = Bench(_base(), _uni(), _base(), _uni())
    ctx, e = await b.essay()
    a = b.inst("A")
    await b.reviewer.run(ctx, e.id, [a], refresh=False, locale="en")
    await b.reviewer.run(ctx, e.id, [a], refresh=True, locale="en")
    assert len(b.w.ai.calls) == 4
    got = await b.reviewer.get(ctx, e.id, "en")
    assert not got.base_stale and not got.universities[0].stale
    await b.svc.save(ctx, e.id, 1, {"body": BODY + " extra"})
    got = await b.reviewer.get(ctx, e.id, "en")
    assert got.base_stale and got.universities[0].stale
    assert len(b.w.ai.calls) == 4


async def test_word_floor_is_fifty() -> None:
    """ADM-REV-3: 49 words are refused, 50 words are reviewed."""
    b = Bench(_base())
    ctx, e = await b.essay(" ".join(["word"] * 49))
    with pytest.raises(EssayTooShortError) as err:
        await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert err.value.params == {"min": 50, "count": 49}
    await b.svc.save(ctx, e.id, 1, {"body": " ".join(["word"] * 50)})
    r = await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert r.base is not None and r.universities == ()


async def test_at_most_five_universities() -> None:
    """ADM-REV-4: five universities pass the limit, six are refused."""
    b = Bench(_base(), *[_uni() for _ in range(5)])
    ctx, e = await b.essay()
    ids = [b.inst(f"U{i}") for i in range(6)]
    with pytest.raises(ItemLimitError):
        await b.reviewer.run(ctx, e.id, ids, refresh=False, locale="en")
    r = await b.reviewer.run(ctx, e.id, ids[:5] + ids[:1], refresh=False, locale="en")
    assert len(r.universities) == 5


async def test_unsourced_university_costs_nothing() -> None:
    """ADM-REV-5: a university without sourced goals gets no call and no quota."""
    b = Bench(_base())
    ctx, e = await b.essay()
    r = await b.reviewer.run(
        ctx, e.id, [b.inst("A", False)], refresh=False, locale="en"
    )
    assert len(b.w.ai.calls) == 1 and b.hits.count == 1
    assert not r.universities[0].review.sourced


async def test_quota_boundary() -> None:
    """ADM-REV-6: the weekly limit counts real calls only."""
    b = Bench(_base(), _uni(), quota=1)
    ctx, e = await b.essay()
    with pytest.raises(RateLimitedError):
        await b.reviewer.run(ctx, e.id, [b.inst("A")], refresh=False, locale="en")
    assert len(b.w.ai.calls) == 1


async def test_foreign_essay_unknown_uni_and_consent() -> None:
    """ADM-REV-7: another student's essay is 404; unknown university 404; consent."""
    b = Bench(_base())
    ctx, e = await b.essay()
    with pytest.raises(AdmissionNotFoundError):
        await b.reviewer.run(ctx, e.id, [new_id()], refresh=False, locale="en")
    b.consents.grants[OTHER] = frozenset({AI})
    other = await b.w.ctx(OTHER)
    with pytest.raises(AdmissionNotFoundError):
        await b.reviewer.run(other, e.id, [], refresh=False, locale="en")
    with pytest.raises(AdmissionNotFoundError):
        await b.reviewer.get(other, e.id, "en")
    b.consents.grants[STUDENT] = frozenset({STAFF_VIEW})
    with pytest.raises(ConsentRequiredError):
        await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert b.w.ai.calls == []


async def test_fake_quotes_and_unknown_patterns_are_dropped() -> None:
    """ADM-REV-8: quotes not in the essay and patterns of unlisted exemplars drop."""
    ex = Exemplar(
        id=new_id(),
        institution_id=None,
        school_name="Yale",
        year=2024,
        kind="personal_statement",
        prompt="",
        title="Radio",
        body="An exemplar body.",
        word_count=3,
        source_url="http://ex",
        source_name="ex",
        tags=(),
        notes="",
        status="published",
        language="en",
        created_by=None,
        updated_by=None,
        created_at=NOW,
        updated_at=NOW,
        lock_version=0,
    )
    reply = _base(
        patterns=[
            {"exemplar_id": str(ex.id), "pattern": "Open on an object"},
            {"exemplar_id": str(new_id()), "pattern": "Invented"},
        ]
    )
    reply["dimensions"][0]["quote"] = "a sentence I never wrote"
    b = Bench(reply)
    b.exemplars.matches = (ExemplarMatch(ex, 0.9),)
    ctx, e = await b.essay()
    r = await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert r.base is not None
    assert r.base.dimensions[0].quote is None
    assert r.base.dimensions[1].quote == "I fixed the old radio"
    assert [p.exemplar_id for p in r.base.patterns] == [ex.id]


def test_fairness_text_in_every_prompt() -> None:
    """ADM-REV-9: the fairness rule is in the base, uni, feedback and check prompts."""
    for text in (
        essay_review.BASE,
        essay_review.UNI,
        coach_prompts.FEEDBACK,
        coach_prompts.CHECK,
    ):
        assert coach_prompts.FAIRNESS in text


async def test_check_is_stored_and_latest_reports_stale() -> None:
    """ADM-REV-10: the coach check is stored; latest_check reads it without a call."""
    reply = {
        "dimensions": [],
        "prompt_fit": "yes",
        "prompt_fit_reason": "",
        "strongest": "voice",
        "first_fix": "",
        "flagged_paragraph": None,
        "flagged_text": None,
        "flagged_reason": "",
        "summary": "ok",
    }
    b = Bench(reply)
    ctx, e = await b.essay()
    with pytest.raises(AdmissionNotFoundError):
        await b.coach.latest_check(ctx, e.id, "en")
    c = await b.coach.check(ctx, e.id, "en")
    [row] = b.reviews.rows
    assert row.kind == "check" and row.institution_id is None
    got, stale, at = await b.coach.latest_check(ctx, e.id, "en")
    assert got == c and not stale and at == b.clock.now()
    await b.svc.save(ctx, e.id, 1, {"body": BODY + " extra"})
    assert (await b.coach.latest_check(ctx, e.id, "en"))[1]
    assert len(b.w.ai.calls) == 1
    with pytest.raises(AdmissionNotFoundError):
        await b.coach.latest_check(await b.w.ctx(OTHER), e.id, "en")


def _degenerate(**kw: Any) -> dict[str, Any]:
    reply = _base(**kw)
    for d in reply["dimensions"]:
        d["score"] = 0
    return reply


@pytest.mark.parametrize("bad", [_degenerate(), _base(summary="")])
async def test_degenerate_first_output_is_retried_once_and_the_valid_one_stored(
    bad: dict[str, Any],
) -> None:
    """ADM-REV-FAIR-1: an all-zero or empty-feedback review is retried once."""
    b = Bench(bad, _base())
    ctx, e = await b.essay()
    r = await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert r.base is not None and r.base.score == 60
    assert len(b.w.ai.calls) == 2
    assert [s.kind for s in b.reviews.rows] == ["base"]
    assert b.hits.count == 1


async def test_two_degenerate_outputs_raise_the_provider_error_and_store_nothing() -> (
    None
):
    """ADM-REV-FAIR-1: two degenerate outputs take the AI-provider error path."""
    b = Bench(_degenerate(), _degenerate())
    ctx, e = await b.essay()
    with pytest.raises(AiProviderError):
        await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert len(b.w.ai.calls) == 2
    assert b.reviews.rows == []
    assert b.hits.count == 1


def test_identity_neutral_line_is_in_every_review_prompt_once() -> None:
    """ADM-REV-FAIR-2: base and university prompts carry the neutral line once."""
    for text in (essay_review.BASE, essay_review.UNI):
        assert essay_review.IDENTITY_NEUTRAL in text
        assert text.count(essay_review.IDENTITY_NEUTRAL) == 1
        assert coach_prompts.FAIRNESS in text
    assert "{" not in essay_review.IDENTITY_NEUTRAL


async def test_a_valid_review_is_not_retried() -> None:
    """ADM-REV-FAIR-3: a normal review costs one call and keeps its dimensions."""
    b = Bench(_base())
    ctx, e = await b.essay()
    r = await b.reviewer.run(ctx, e.id, [], refresh=False, locale="en")
    assert len(b.w.ai.calls) == 1
    assert r.base is not None and all(d.score == 3 for d in r.base.dimensions)
