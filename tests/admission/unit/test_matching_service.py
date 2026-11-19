"""Matches and swipe decisions over in-memory repositories."""

import datetime as dt
from types import SimpleNamespace
from typing import Any
from uuid import UUID

from app.modules.admission.application.matching import MatchService
from app.modules.admission.domain.chooser import CatalogInstitution, ListEntry
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
)
from app.modules.admission.domain.matching import PreferenceAnswers
from app.shared.ids import new_id
from tests.fakes.clock import FixedClock

import pytest

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.UTC)


class Prefs:
    def __init__(self) -> None:
        self.rows: dict[UUID, tuple[PreferenceAnswers, dt.datetime]] = {}

    async def get(self, sid: UUID) -> Any:
        return self.rows.get(sid)

    async def save(self, sid: UUID, a: PreferenceAnswers, at: dt.datetime) -> None:
        self.rows[sid] = (a, at)


class Decisions:
    def __init__(self) -> None:
        self.rows: dict[tuple[UUID, UUID], str] = {}
        self.created: set[tuple[UUID, UUID]] = set()

    async def decided(self, sid: UUID) -> set[UUID]:
        return {i for (s, i) in self.rows if s == sid}

    async def get(self, sid: UUID, iid: UUID) -> str | None:
        return self.rows.get((sid, iid))

    async def created_entry(self, sid: UUID, iid: UUID) -> bool:
        return (sid, iid) in self.created

    async def set(
        self,
        sid: UUID,
        iid: UUID,
        d: str,
        at: dt.datetime,
        *,
        created_list_entry: bool = False,
    ) -> None:
        self.rows[(sid, iid)] = d
        if created_list_entry:
            self.created.add((sid, iid))
        else:
            self.created.discard((sid, iid))

    async def delete(self, sid: UUID, iid: UUID) -> None:
        self.rows.pop((sid, iid), None)
        self.created.discard((sid, iid))


class Catalog:
    def __init__(self, items: list[CatalogInstitution]) -> None:
        self.items = items

    async def institutions(self) -> list[CatalogInstitution]:
        return self.items

    async def institution(self, iid: UUID) -> CatalogInstitution | None:
        return next((i for i in self.items if i.id == iid), None)


class Shortlist:
    def __init__(self) -> None:
        self.rows: dict[UUID, ListEntry] = {}

    async def find(self, sid: UUID, iid: UUID) -> ListEntry | None:
        return next((e for e in self.rows.values() if e.institution_id == iid), None)

    async def entries(self, sid: UUID) -> list[ListEntry]:
        return [e for e in self.rows.values() if e.student_id == sid]

    async def delete(self, entry_id: UUID) -> None:
        self.rows.pop(entry_id, None)


class Uow:
    def __init__(self, world: "World") -> None:
        self.preferences = world.prefs
        self.decisions = world.decisions
        self.catalog = world.catalog
        self.shortlist = world.shortlist

    async def __aenter__(self) -> "Uow":
        return self

    async def __aexit__(self, *exc: object) -> None:
        return None

    async def commit(self) -> None:
        return None


class Chooser:
    def __init__(self, world: "World") -> None:
        self.world = world
        self.calls = 0

    async def add(self, ctx: Any, iid: UUID) -> None:
        self.calls += 1
        if await self.world.shortlist.find(ctx.user_id, iid) is None:
            e = ListEntry(id=new_id(), student_id=ctx.user_id, institution_id=iid)
            self.world.shortlist.rows[e.id] = e


def _inst(name: str, country: str) -> CatalogInstitution:
    return CatalogInstitution(
        id=new_id(), slug=None, name=name, country=country, city=None,
        status="published",
    )  # fmt: skip


class World:
    def __init__(self) -> None:
        self.us = _inst("Alpha", "US")
        self.uk = _inst("Beta", "UK")
        self.prefs, self.decisions = Prefs(), Decisions()
        self.catalog = Catalog([self.uk, self.us])
        self.shortlist = Shortlist()
        self.chooser = Chooser(self)
        self.svc = MatchService(
            lambda: Uow(self), self.chooser, FixedClock(NOW)  # type: ignore
        )
        self.ctx: Any = SimpleNamespace(
            user_id=new_id(), admission=SimpleNamespace(is_applicant=True)
        )


async def test_preferences_partial_merge() -> None:
    w = World()
    assert (await w.svc.preferences(w.ctx)).updated_at is None
    await w.svc.save_preferences(w.ctx, {"setting": ["city", "city", "rural"]})
    v = await w.svc.save_preferences(w.ctx, {"region": ["us"]})
    assert v.tags == ["setting:city", "setting:rural", "region:US"]
    assert not v.completed and v.updated_at == NOW


async def test_matches_rank_and_exclude_decided() -> None:
    w = World()
    await w.svc.save_preferences(w.ctx, {"region": ["US"]})
    items = await w.svc.matches(w.ctx, 20)
    assert [m.institution.name for m in items] == ["Alpha", "Beta"]
    assert items[0].match_pct == 100 and items[1].match_pct == 0
    await w.svc.decide(w.ctx, w.us.id, "not_my_vibe")
    items = await w.svc.matches(w.ctx, 20)
    assert [m.institution.name for m in items] == ["Beta"]


async def test_interested_is_idempotent_and_undo_removes() -> None:
    w = World()
    await w.svc.decide(w.ctx, w.us.id, "interested")
    await w.svc.decide(w.ctx, w.us.id, "interested")
    assert len(w.shortlist.rows) == 1
    assert len(w.decisions.rows) == 1
    await w.svc.undo(w.ctx, w.us.id)
    assert not w.decisions.rows and not w.shortlist.rows
    await w.svc.undo(w.ctx, w.us.id)


async def test_unknown_university_404() -> None:
    w = World()
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.decide(w.ctx, new_id(), "interested")
    with pytest.raises(AdmissionNotFoundError):
        await w.svc.undo(w.ctx, new_id())


async def test_undo_keeps_preexisting_list_entry() -> None:
    w = World()
    e = ListEntry(id=new_id(), student_id=w.ctx.user_id, institution_id=w.us.id)
    w.shortlist.rows[e.id] = e
    await w.svc.decide(w.ctx, w.us.id, "interested")
    assert not w.decisions.created
    await w.svc.undo(w.ctx, w.us.id)
    assert e.id in w.shortlist.rows and not w.decisions.rows


async def test_change_of_mind_removes_only_created_entry() -> None:
    w = World()
    await w.svc.decide(w.ctx, w.us.id, "interested")
    assert w.decisions.created and len(w.shortlist.rows) == 1
    await w.svc.decide(w.ctx, w.us.id, "not_my_vibe")
    assert not w.shortlist.rows and not w.decisions.created
    pre = ListEntry(id=new_id(), student_id=w.ctx.user_id, institution_id=w.uk.id)
    w.shortlist.rows[pre.id] = pre
    await w.svc.decide(w.ctx, w.uk.id, "interested")
    await w.svc.decide(w.ctx, w.uk.id, "not_my_vibe")
    assert pre.id in w.shortlist.rows


async def test_matches_exclude_shortlisted() -> None:
    w = World()
    e = ListEntry(id=new_id(), student_id=w.ctx.user_id, institution_id=w.us.id)
    w.shortlist.rows[e.id] = e
    items = await w.svc.matches(w.ctx, 20)
    assert [m.institution.name for m in items] == ["Beta"]


async def test_writes_require_applicant() -> None:
    w = World()
    w.ctx.admission.is_applicant = False
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.save_preferences(w.ctx, {"setting": ["city"]})
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.decide(w.ctx, w.us.id, "interested")
    with pytest.raises(AdmissionForbiddenError):
        await w.svc.undo(w.ctx, w.us.id)
