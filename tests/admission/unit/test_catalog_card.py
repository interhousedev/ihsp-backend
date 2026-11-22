"""Curator card service: permissions, audit, lock conflict, fact cleaning."""

from typing import Any
from uuid import UUID

from app.modules.admission.application.catalog_card import CatalogCardService
from app.modules.admission.application.catalog_proposals import CatalogProposalService
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    CatalogFactInvalidError,
)
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World
from tests.fakes.clock import FixedClock

import pytest

IID = new_id()


class _Inst:
    def __init__(self, lock: int) -> None:
        self.lock_version = lock


class _Staff:
    def __init__(self) -> None:
        self.lock = 3

    async def update_institution(
        self, iid: UUID, values: dict[str, Any], *, expected_lock: int
    ) -> bool:
        if expected_lock != self.lock:
            raise AdmissionConflictError()
        self.lock += 1
        return True

    async def get_institution(self, iid: UUID) -> _Inst:
        return _Inst(self.lock)


class _Card:
    def __init__(self) -> None:
        self.scholarships: list[dict[str, Any]] = []
        self.description: Any = None

    async def create_scholarship(self, iid: UUID, values: dict[str, Any]) -> UUID:
        self.scholarships.append(values)
        return new_id()

    async def set_description(self, iid: UUID, value: Any, now: Any) -> None:
        self.description = value


class _Apply:
    def __init__(self) -> None:
        self.facts: dict[str, Any] = {}

    async def apply_facts(self, iid: UUID, facts: Any, rid: UUID, now: Any) -> None:
        self.facts.update(facts)


def _svc(w: World) -> tuple[CatalogCardService, _Staff, _Card, _Apply, list[Any]]:
    staff, card, apply = _Staff(), _Card(), _Apply()
    audits: list[Any] = []

    def factory() -> FakeUow:
        uow = FakeUow(w.store)
        uow.catalog_staff = staff  # type: ignore[assignment]
        uow.catalog_card = card  # type: ignore[attr-defined]
        uow.catalog_proposals = apply  # type: ignore[assignment]
        return uow

    can = CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW)).can_review
    return CatalogCardService(factory, can, FixedClock(NOW)), staff, card, apply, audits


FACT = {
    "value": {"amount": 100, "currency": "USD"},
    "source_url": "https://x.org",
    "year": 2026,
}


async def test_counselor_saves_facts_and_lock_moves() -> None:
    w = World()
    svc, staff, _, apply, _ = _svc(w)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    lock = await svc.save_facts(ctx, IID, {"intl_coa_usd": FACT}, [], lock_version=3)
    assert lock == 4 and "intl_coa_usd" in apply.facts
    assert [e.action for e in w.store.audit] == ["catalog.facts_edited"]


async def test_stale_lock_conflicts() -> None:
    w = World()
    svc, *_ = _svc(w)
    ctx = await w.ctx(STAFF, Role.ADMIN)
    with pytest.raises(AdmissionConflictError):
        await svc.save_facts(ctx, IID, {"intl_coa_usd": FACT}, [], lock_version=1)


@pytest.mark.parametrize("role", [Role.TEACHER, Role.STUDENT])
async def test_non_curators_are_denied(role: Role) -> None:
    w = World()
    svc, *_ = _svc(w)
    ctx = await w.ctx(STUDENT, role)
    with pytest.raises(AdmissionForbiddenError):
        await svc.save_facts(ctx, IID, {"intl_coa_usd": FACT}, [], lock_version=3)
    with pytest.raises(AdmissionForbiddenError):
        await svc.create_scholarship(ctx, IID, {"name": "A"}, lock_version=3)


async def test_invalid_fact_and_scholarship_are_rejected() -> None:
    w = World()
    svc, _, card, _, _ = _svc(w)
    ctx = await w.ctx(STAFF, Role.ADMIN)
    bad = {**FACT, "source_url": "http://x.org"}
    with pytest.raises(CatalogFactInvalidError):
        await svc.save_facts(ctx, IID, {"intl_coa_usd": bad}, [], lock_version=3)
    with pytest.raises(ValidationFailedError):
        await svc.create_scholarship(ctx, IID, {"name": "A"}, lock_version=3)
    await svc.create_scholarship(
        ctx,
        IID,
        {"name": "A", "provider": "institution", "basis": "merit"},
        lock_version=3,
    )
    assert card.scholarships[0]["name"] == "A"


async def test_blank_optional_scholarship_fields_are_accepted() -> None:
    w = World()
    svc, _, card, _, _ = _svc(w)
    ctx = await w.ctx(STAFF, Role.ADMIN)
    await svc.create_scholarship(
        ctx,
        IID,
        {
            "name": "A",
            "provider": "institution",
            "basis": "merit",
            "country": None,
            "url": None,
            "cycle": None,
            "coverage_pct_max": 50,
            "covers": [],
        },
        lock_version=3,
    )
    assert card.scholarships[0]["name"] == "A"
    with pytest.raises(ValidationFailedError):
        await svc.create_scholarship(
            ctx,
            IID,
            {"name": "A", "provider": "institution", "basis": "merit", "country": "X"},
            lock_version=3,
        )


async def test_description_is_cleaned_per_locale() -> None:
    w = World()
    svc, _, card, _, _ = _svc(w)
    ctx = await w.ctx(STAFF, Role.ADMIN)
    await svc.save_description(ctx, IID, {"en": " Hi ", "ru": " "}, lock_version=3)
    assert card.description == {"en": "Hi"}
    with pytest.raises(ValidationFailedError):
        await svc.save_description(ctx, IID, {"de": "x"}, lock_version=4)
