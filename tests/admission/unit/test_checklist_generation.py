"""Checklist generation: per round, idempotent, stable title keys."""

from app.modules.admission.domain.checklist import entry_items, shared_items
from app.modules.admission.domain.chooser import ListEntry
from app.shared.ids import new_id
from tests.admission.unit.test_chooser_service import World


def test_shared_items_skip_existing() -> None:
    sid = new_id()
    first = shared_items(sid, [])
    assert {i.title_key for i in first} == {"transcript", "passport", "translation"}
    assert shared_items(sid, first) == []


def test_binding_round_adds_agreement() -> None:
    sid = new_id()
    rd = {
        i.template_key
        for i in entry_items(ListEntry(new_id(), sid, new_id(), "RD"), [])
    }
    ed = {
        i.template_key
        for i in entry_items(ListEntry(new_id(), sid, new_id(), "ED"), [])
    }
    assert "entry.binding_agreement" not in rd
    assert ed - rd == {"entry.binding_agreement"}


async def test_add_to_list_generates_once() -> None:
    w = World()
    ctx = await w.student()
    iid = w.inst()
    await w.lists.add(ctx, iid)
    n = len(w.store.checklist)
    assert n > 3
    await w.lists.add(ctx, iid)
    assert len(w.store.checklist) == n
    assert {i.list_entry_id is None for i in w.store.checklist} == {True, False}
