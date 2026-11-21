"""Prompt map and idea fit with fake vectors."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_prompt_map import EssayPromptMap
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.chooser import ListEntry
from app.modules.admission.domain.errors import (
    ConsentRequiredError,
    InvalidAnswerError,
)
from app.modules.admission.domain.essay_flow import (
    PromptRef,
    PromptTarget,
    SlotAssignment,
    build_map,
    cluster,
    fit_score,
    prompt_key,
)
from app.modules.admission.domain.essays import Essay
from app.modules.admission.infrastructure.essay_crypto import (
    AesGcmEssayCipher,
    MemoryEssayKeyStore,
)
from app.shared.ids import new_id
from tests.admission.unit.fakes_flow import (
    FakeVectors,
    MemIdeaFits,
    MemPrompts,
    MemSlots,
)
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_items_service import STUDENT, ItemsUow

import pytest

UNI_A, UNI_B = new_id(), new_id()
TEXT = "zebra quokka marmalade telescope harpsichord"


def _ref(inst: UUID, pos: int, prompt: str) -> PromptRef:
    return PromptRef(prompt_key(inst, pos), inst, f"U{str(inst)[:4]}", pos, prompt, 250)


REFS = [
    _ref(UNI_A, 0, TEXT),
    _ref(UNI_B, 0, TEXT),
    _ref(UNI_B, 1, "why this campus fits your plans for studying robotics"),
]


def _svc(
    d: Desk, vectors: FakeVectors, refs: list[PromptRef] | None = None
) -> tuple[EssayPromptMap, MemSlots]:
    slots = MemSlots()
    fits = MemIdeaFits()
    prompts = MemPrompts(REFS if refs is None else refs)

    def uow() -> Any:
        u = ItemsUow(d.w.store, d.w.data)
        u.essays = d.repo  # type: ignore[attr-defined]
        u.prompt_catalog = prompts  # type: ignore[attr-defined]
        u.slots = slots  # type: ignore[attr-defined]
        u.idea_fits = fits  # type: ignore[attr-defined]
        return u

    gate = FlowGate(d.w.policy, d.consents)
    return (
        EssayPromptMap(uow, gate, vectors, AesGcmEssayCipher(MemoryEssayKeyStore())),
        slots,
    )


def test_cluster_groups_close_prompts_but_not_same_owner() -> None:
    vecs = [[1.0, 0.0], [1.0, 0.01], [0.0, 1.0]]
    assert cluster(vecs, ["a", "b", "c"], 0.1) == [[0, 1], [2]]
    assert cluster(vecs, ["a", "a", "c"], 0.1) == [[0], [1], [2]]


def test_build_map_without_vectors_is_all_unique() -> None:
    m = build_map(REFS, None, model="none")
    assert not m.clustered
    assert [g.kind for g in m.groups] == ["unique"] * 3


def test_fit_score_bounds() -> None:
    assert fit_score(0.0, 0.4) == 100
    assert fit_score(0.8, 0.4) == 0
    assert 0 < fit_score(0.4, 0.4) < 100


async def test_map_clusters_shared_prompt_and_marks_list() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    d.w.store.list_entries[new_id()] = ListEntry(new_id(), STUDENT, UNI_A)
    svc, _ = _svc(d, FakeVectors())
    view = await svc.prompt_map(ctx)
    assert view.available
    shared = [g for g in view.map.groups if g.kind == "shared"]
    assert len(shared) == 1 and len(shared[0].prompts) == 2
    marked = {p.key: p.in_list for g in view.map.groups for p in g.prompts}
    assert marked[prompt_key(UNI_A, 0)] and not marked[prompt_key(UNI_B, 0)]


async def test_map_unavailable_when_vectors_missing() -> None:
    d = Desk()
    svc, _ = _svc(d, FakeVectors(offline=True))
    view = await svc.prompt_map(await d.w.ctx())
    assert not view.available
    assert all(g.kind != "shared" for g in view.map.groups)


async def test_fit_ranks_and_skips_covered() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    svc, slots = _svc(d, FakeVectors())
    out = await svc.fit(ctx, TEXT)
    assert out.available
    top = out.items[0]
    assert top.score == 100 and top.prompt.prompt == TEXT
    covered_key = prompt_key(UNI_A, 0)
    e = Essay(new_id(), STUDENT, targets=(PromptTarget(UNI_A, 0, TEXT),))
    await d.repo.add(e)
    await slots.put(SlotAssignment(STUDENT, UNI_B, "supp:1", e.id))
    out = await svc.fit(ctx, TEXT)
    keys = {f.prompt.key for f in out.items}
    assert covered_key not in keys and prompt_key(UNI_B, 1) not in keys
    assert prompt_key(UNI_B, 0) in keys


async def test_fit_needs_consent_owner_and_text() -> None:
    d = Desk(consent=False)
    svc, _ = _svc(d, FakeVectors())
    ctx = await d.w.ctx()
    with pytest.raises(ConsentRequiredError):
        await svc.fit(ctx, TEXT)
    d2 = Desk()
    svc2, _ = _svc(d2, FakeVectors())
    with pytest.raises(InvalidAnswerError):
        await svc2.fit(await d2.w.ctx(), "   ")


async def test_fit_unavailable_offline() -> None:
    d = Desk()
    svc, _ = _svc(d, FakeVectors(offline=True))
    out = await svc.fit(await d.w.ctx(), TEXT)
    assert not out.available and out.items == ()


async def test_fit_is_cached_and_cache_only_never_calls_model() -> None:
    d = Desk()
    ctx = await d.w.ctx()
    vectors = FakeVectors()
    svc, _ = _svc(d, vectors)
    pending = await svc.fit(ctx, TEXT, cached_only=True)
    assert pending.pending and not pending.cached and pending.items == ()
    first = await svc.fit(ctx, TEXT)
    assert first.available and not first.cached
    vectors.offline = True
    again = await svc.fit(ctx, TEXT)
    assert again.cached and again.available
    assert [f.score for f in again.items] == [f.score for f in first.items]
