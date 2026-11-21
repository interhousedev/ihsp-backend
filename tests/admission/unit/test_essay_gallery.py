"""Gallery: publish with consent, anonymous browse, fork a target."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.essay_gallery import EssayGalleryService
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    ConsentRequiredError,
    EssayTooShortError,
    ForkLastTargetError,
)
from app.modules.admission.domain.essay_flow import PromptTarget
from app.modules.admission.ports.consent import SHARING
from app.shared.ids import new_id
from tests.admission.unit.fakes_flow import MemGallery
from tests.admission.unit.test_essays import Desk
from tests.admission.unit.test_items_service import OTHER, STUDENT

import pytest

UNI = new_id()


class Hall(Desk):
    def __init__(self, sharing: set[UUID] | None = None) -> None:
        super().__init__()
        self.gallery = MemGallery()
        allowed = {STUDENT, OTHER} if sharing is None else sharing
        for u in (STUDENT, OTHER):
            self.consents.grants[u] = frozenset({SHARING} if u in allowed else ())

        def uow() -> Any:
            from tests.admission.unit.test_items_service import ItemsUow

            u = ItemsUow(self.w.store, self.w.data)
            u.essays = self.repo  # type: ignore[attr-defined]
            u.gallery = self.gallery  # type: ignore[attr-defined]
            return u

        self.hall = EssayGalleryService(
            uow, FlowGate(self.w.policy, self.consents), self.clock
        )


async def _essay(h: Hall, user: UUID, body: str = "hello world") -> Any:
    ctx = await h.w.ctx(user)
    e = await h.svc.create(ctx, {"title": "T", "body": body})
    return ctx, e


async def test_publish_snapshots_and_needs_sharing() -> None:
    h = Hall(sharing=set())
    ctx, e = await _essay(h, STUDENT)
    with pytest.raises(ConsentRequiredError):
        await h.hall.publish(ctx, e.id)
    h.consents.grants[STUDENT] = frozenset({SHARING})
    item = await h.hall.publish(ctx, e.id)
    assert item.version == 1 and item.body == "hello world"
    await h.svc.save(ctx, e.id, 1, {"body": "changed after"})
    view = await h.hall.browse(ctx)
    assert view.mine[0].body == "hello world" and view.items == []


async def test_empty_body_cannot_be_published() -> None:
    h = Hall()
    ctx, e = await _essay(h, STUDENT, body="")
    with pytest.raises(EssayTooShortError):
        await h.hall.publish(ctx, e.id)


async def test_browse_hides_non_sharing_authors_and_own() -> None:
    h = Hall()
    mine_ctx, mine = await _essay(h, STUDENT)
    other_ctx, other = await _essay(h, OTHER, "other text")
    await h.hall.publish(mine_ctx, mine.id)
    await h.hall.publish(other_ctx, other.id)
    view = await h.hall.browse(mine_ctx)
    assert [i.essay_id for i in view.items] == [other.id]
    assert [i.essay_id for i in view.mine] == [mine.id]
    h.consents.grants[OTHER] = frozenset()
    assert (await h.hall.browse(mine_ctx)).items == []


async def test_unpublish_is_owner_only() -> None:
    h = Hall()
    ctx, e = await _essay(h, STUDENT)
    await h.hall.publish(ctx, e.id)
    with pytest.raises(AdmissionNotFoundError):
        await h.hall.unpublish(await h.w.ctx(OTHER), e.id)
    await h.hall.unpublish(ctx, e.id)
    assert (await h.hall.browse(ctx)).mine == []


async def test_fork_takes_target_from_parent() -> None:
    h = Hall()
    ctx = await h.w.ctx(STUDENT)
    t1 = PromptTarget(UNI, 1, "Why us?", 250)
    t2 = PromptTarget(UNI, 2, "Community?", 150)
    e = await h.svc.create(ctx, {"body": "shared body", "targets": [t1, t2]})
    parent, child = await h.hall.fork(ctx, e.id, UNI, 2)
    assert [t.position for t in parent.targets] == [1]
    assert child.targets == (t2,) and child.forked_from == e.id
    assert child.body == "shared body" and child.word_limit == 150
    with pytest.raises(AdmissionNotFoundError):
        await h.hall.fork(ctx, e.id, UNI, 2)
    with pytest.raises(AdmissionNotFoundError):
        await h.hall.fork(await h.w.ctx(OTHER), e.id, UNI, 1)


async def test_fork_position_zero_is_valid() -> None:
    h = Hall()
    ctx = await h.w.ctx(STUDENT)
    t0 = PromptTarget(UNI, 0, "Personal statement", 650)
    t1 = PromptTarget(UNI, 1, "Why us?", 250)
    e = await h.svc.create(ctx, {"body": "shared body", "targets": [t0, t1]})
    parent, child = await h.hall.fork(ctx, e.id, UNI, 0)
    assert child.targets == (t0,) and parent.targets == (t1,)


async def test_fork_of_last_supplemental_target_is_rejected() -> None:
    h = Hall()
    ctx = await h.w.ctx(STUDENT)
    t1 = PromptTarget(UNI, 1, "Why us?", 250)
    e = await h.svc.create(
        ctx, {"kind": "supplemental", "body": "text", "targets": [t1]}
    )
    with pytest.raises(ForkLastTargetError):
        await h.hall.fork(ctx, e.id, UNI, 1)


async def test_published_card_keeps_title_and_prompt_as_published() -> None:
    h = Hall()
    ctx = await h.w.ctx(STUDENT)
    t1 = PromptTarget(UNI, 1, "Why us?", 250)
    e = await h.svc.create(
        ctx, {"title": "Old", "body": "hello world", "targets": [t1]}
    )
    await h.hall.publish(ctx, e.id)
    await h.svc.save(ctx, e.id, 1, {"title": "New", "body": "hello world"})
    mine = (await h.hall.browse(ctx)).mine[0]
    assert mine.title == "Old" and mine.targets == (t1,)
