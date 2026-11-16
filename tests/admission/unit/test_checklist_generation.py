"""Checklist generation: per round, idempotent, stable title keys."""

import datetime as dt
from typing import Any

from app.modules.admission.domain.checklist import (
    clean_source_url,
    deep_link,
    entry_items,
    is_urgent,
    quadrant,
    shared_items,
)
from app.modules.admission.domain.chooser import ListEntry
from app.modules.admission.domain.documents import ChecklistItem
from app.modules.admission.domain.errors import InvalidProofUrlError
from app.shared.ids import new_id
from tests.admission.unit.test_chooser_service import World

import pytest


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


# -- priority ---------------------------------------------------------------

NOW = dt.datetime(2026, 11, 16, 12, tzinfo=dt.UTC)


def _item(**kw: Any) -> ChecklistItem:
    return ChecklistItem(
        id=new_id(),
        student_id=new_id(),
        template_key="entry.essay",
        title_key="essay",
        **kw,
    )


def test_urgent_by_deadline_proximity() -> None:
    assert is_urgent(_item(due_utc=NOW + dt.timedelta(days=3)), NOW)
    assert is_urgent(_item(due_utc=NOW - dt.timedelta(days=1)), NOW)
    assert not is_urgent(_item(due_utc=NOW + dt.timedelta(days=30)), NOW)
    assert not is_urgent(_item(), NOW)


def test_urgent_override_wins_but_done_never_urgent() -> None:
    far = NOW + dt.timedelta(days=30)
    assert is_urgent(_item(due_utc=far, urgent_override=True), NOW)
    assert not is_urgent(
        _item(due_utc=NOW + dt.timedelta(days=1), urgent_override=False), NOW
    )
    assert not is_urgent(_item(due_utc=NOW, urgent_override=True, status="done"), NOW)


def test_quadrants() -> None:
    soon = NOW + dt.timedelta(days=1)
    assert quadrant(_item(important=True, due_utc=soon), NOW) == "do"
    assert quadrant(_item(important=True), NOW) == "schedule"
    assert quadrant(_item(due_utc=soon), NOW) == "delegate"
    assert quadrant(_item(), NOW) == "drop"


def test_deep_links_and_source_url() -> None:
    assert deep_link("entry.essay") == "/essays/"
    assert deep_link("entry.fee") is None
    assert clean_source_url("  ") is None
    assert clean_source_url(" https://x.uz/a ") == "https://x.uz/a"
    with pytest.raises(InvalidProofUrlError):
        clean_source_url("javascript:alert(1)")
