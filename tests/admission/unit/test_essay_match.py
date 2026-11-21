"""Top essays and the matching table over stored reviews."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_match import EssayMatchService
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.chooser import (
    CatalogInstitution,
    FactView,
    ListEntry,
)
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.essay_categories import ShortAnswer
from app.modules.admission.domain.essay_flow import PromptRef, PromptTarget, prompt_key
from app.modules.admission.domain.essay_reviews import StoredReview
from app.modules.admission.domain.essays import Essay
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes_flow import MemPrompts, MemShortAnswers, MemSlots
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_items_service import STUDENT, ItemsUow

import pytest

UNI = new_id()
OTHER = new_id()
NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


class Bench(Desk):
    def __init__(self) -> None:
        super().__init__()
        self.slots = MemSlots()
        self.answers = MemShortAnswers()
        self.prompts = MemPrompts(
            [
                PromptRef(prompt_key(UNI, 0), UNI, "U", 0, "Why us?", 250),
                PromptRef(prompt_key(UNI, 1), UNI, "U", 1, "A community", 150),
            ]
        )
        for iid in (UNI, OTHER):
            self.w.store.institutions[iid] = CatalogInstitution(
                iid, str(iid), "Uni", "US", None, "published", {}
            )

        def uow() -> Any:
            u = ItemsUow(self.w.store, self.w.data)
            u.essays = self.repo  # type: ignore[attr-defined]
            u.essay_reviews = self.reviews  # type: ignore[attr-defined]
            u.prompt_catalog = self.prompts  # type: ignore[attr-defined]
            u.slots = self.slots  # type: ignore[attr-defined]
            u.short_answers = self.answers  # type: ignore[attr-defined]
            return u

        self.match = EssayMatchService(uow, FlowGate(self.w.policy, self.consents))

    async def essay(
        self,
        kind: str = "personal_statement",
        words: int = 10,
        targets: tuple[PromptTarget, ...] = (),
        owner: UUID = STUDENT,
    ) -> Essay:
        e = Essay(
            new_id(),
            owner,
            kind=kind,  # type: ignore[arg-type]
            title=f"{kind}-{words}",
            body="w " * words,
            targets=targets,
        )
        return await self.repo.add(e)

    def review(
        self, e: Essay, kind: str, payload: dict[str, Any], uni: UUID | None = None
    ) -> None:
        self.reviews.rows.append(
            StoredReview(
                new_id(),
                e.id,
                e.student_id,
                kind,  # type: ignore[arg-type]
                uni,
                "d",
                payload,
                "m",
                "p",
                NOW,
            )
        )


async def test_top_sorted_by_base_score_and_capped() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    for i in range(12):
        e = await b.essay(words=i + 1)
        b.review(e, "base", {"score": i * 5, "band": "good"})
    await b.essay(words=99)  # no review: excluded
    rows = await b.match.top(ctx)
    assert len(rows) == 10
    assert [r.score for r in rows] == sorted((r.score for r in rows), reverse=True)
    assert rows[0].score == 55


async def test_table_slots_and_candidate_order() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    ps_low = await b.essay(words=5)
    ps_high = await b.essay(words=3)
    supp = await b.essay("supplemental", 50, (PromptTarget(UNI, 0, "Why us?", 250),))
    plain = await b.essay("supplemental", 80)
    b.review(ps_low, "uni", {"alignment": 40}, UNI)
    b.review(ps_high, "uni", {"alignment": 80}, UNI)
    b.review(ps_low, "uni", {"alignment": 99}, OTHER)
    t = await b.match.table(ctx, UNI)
    assert [s.slot for s in t.slots] == ["ps", "supp:0", "supp:1"]
    ps = t.slots[0]
    assert [c.essay_id for c in ps.candidates] == [ps_high.id, ps_low.id]
    s0 = t.slots[1]
    ids = [c.essay_id for c in s0.candidates]
    assert ids[:2] == [ps_high.id, ps_low.id]  # alignment first
    assert ids.index(supp.id) < ids.index(plain.id)  # target match beats words
    assert next(c for c in s0.candidates if c.essay_id == supp.id).target_match
    assert ids.index(plain.id) < len(ids)


async def test_over_limit_candidates_sort_after_fitting_ones() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    long = await b.essay("supplemental", 200)
    fits = await b.essay("supplemental", 100)
    b.review(long, "uni", {"alignment": 90}, UNI)
    t = await b.match.table(ctx, UNI)
    ids = [c.essay_id for c in t.slots[2].candidates]  # supp:1, limit 150
    assert ids == [fits.id, long.id]


async def test_assign_moves_essay_and_clear() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    e = await b.essay("supplemental", 20)
    await b.match.assign(ctx, UNI, "supp:0", e.id)
    t = await b.match.assign(ctx, UNI, "supp:1", e.id)
    assert [s.essay_id for s in t.slots] == [None, None, e.id]
    t = await b.match.clear(ctx, UNI, "supp:1")
    assert all(s.essay_id is None for s in t.slots)
    await b.match.clear(ctx, UNI, "supp:1")


async def test_ps_slot_only_for_personal_statements() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    supp = await b.essay("supplemental")
    ps = await b.essay()
    with pytest.raises(ValidationFailedError):
        await b.match.assign(ctx, UNI, "ps", supp.id)
    t = await b.match.assign(ctx, UNI, "ps", ps.id)
    assert t.slots[0].essay_id == ps.id
    assert supp.id not in [c.essay_id for c in t.slots[0].candidates]


async def test_rejects_unknown_slot_essay_university_and_foreign_essay() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    e = await b.essay()
    foreign = await b.essay(owner=new_id())
    with pytest.raises(ValidationFailedError):
        await b.match.assign(ctx, UNI, "supp:9", e.id)
    with pytest.raises(ValidationFailedError):
        await b.match.clear(ctx, UNI, "bogus")
    with pytest.raises(AdmissionNotFoundError):
        await b.match.assign(ctx, UNI, "ps", foreign.id)
    with pytest.raises(AdmissionNotFoundError):
        await b.match.assign(ctx, UNI, "ps", new_id())
    with pytest.raises(AdmissionNotFoundError):
        await b.match.table(ctx, new_id())


def _common_app(b: Bench, *ids: UUID) -> None:
    for iid in ids:
        inst = b.w.store.institutions[iid]
        inst.facts["application_platforms"] = FactView(["common_app", "own"])
        b.w.store.list_entries[new_id()] = ListEntry(new_id(), STUDENT, iid)


async def test_common_app_slot_is_one_call_for_every_common_app_university() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    _common_app(b, UNI)
    b.w.store.institutions[OTHER].facts["application_platforms"] = FactView(["ucas"])
    b.w.store.list_entries[new_id()] = ListEntry(new_id(), STUDENT, OTHER)
    ps = await b.essay()
    tables = {t.institution_id: t for t in await b.match.set_common_app(ctx, ps.id)}
    assert tables[UNI].slots[0].shared and tables[UNI].slots[0].essay_id == ps.id
    assert not tables[OTHER].slots[0].shared and tables[OTHER].slots[0].essay_id is None
    cleared = await b.match.set_common_app(ctx, None)
    assert all(t.slots[0].essay_id is None for t in cleared)
    supp = await b.essay("supplemental")
    with pytest.raises(ValidationFailedError):
        await b.match.set_common_app(ctx, supp.id)
    with pytest.raises(AdmissionNotFoundError):
        await b.match.set_common_app(ctx, new_id())


async def test_short_answer_slot_carries_the_sealed_text() -> None:
    b = Bench()
    ctx = await b.w.ctx()
    key = prompt_key(UNI, 2)
    b.prompts.refs.append(PromptRef(key, UNI, "U", 2, "Name a book you loved", 80))
    b.answers.rows[(STUDENT, key)] = ShortAnswer(STUDENT, key, "tiny text", 2)
    b.answers.rows[(STUDENT, prompt_key(UNI, 1))] = ShortAnswer(
        STUDENT, prompt_key(UNI, 1), "x", 1
    )
    t = await b.match.table(ctx, UNI)
    assert t.slots[2].category == "community" and t.slots[2].short_answer is None
    last = t.slots[3]
    assert last.category == "short_answer" and last.prompt_key == key
    assert last.short_answer is not None and last.short_answer.word_count == 2


def test_unknown_platforms_default_to_common_app_only_in_the_us() -> None:
    from app.modules.admission.application.essay_match import uses_common_app

    def inst(facts: dict[str, FactView], country: str = "US") -> CatalogInstitution:
        return CatalogInstitution(new_id(), "s", "U", country, None, "published", facts)

    assert uses_common_app(inst({}))
    assert uses_common_app(inst({"application_platforms": FactView([])}))
    assert not uses_common_app(inst({}, "IT"))
    assert not uses_common_app(inst({}, "UZ"))
    assert uses_common_app(
        inst({"application_platforms": FactView(["common_app"])}, "GB")
    )
    assert not uses_common_app(inst({"application_platforms": FactView(["own"])}))
