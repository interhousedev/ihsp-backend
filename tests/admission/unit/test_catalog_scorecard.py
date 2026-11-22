"""College Scorecard lookup and attach, with a fake HTTP transport."""

import json
from dataclasses import replace
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.application.catalog_scorecard import (
    CatalogScorecardService,
)
from app.modules.admission.domain.catalog_staff import StaffInstitution
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    ScorecardUnavailableError,
)
from app.modules.admission.infrastructure.scorecard_client import HttpScorecardClient
from app.shared.actor import Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World
from tests.fakes.clock import FixedClock

import httpx
import pytest

ROW = {
    "id": 166027,
    "school.name": "Harvard University",
    "school.city": "Cambridge",
    "school.state": "MA",
    "school.locale": 12,
    "school.school_url": "www.harvard.edu/",
    "latest.admissions.admission_rate.overall": 0.0324,
    "latest.admissions.test_requirements": 1,
    "latest.cost.tuition.out_of_state": 57261,
    "latest.cost.attendance.academic_year": 82866,
}


def _client(status: int = 200, rows: list[dict[str, Any]] | None = None) -> Any:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status, json={"results": [ROW] if rows is None else rows})

    client = HttpScorecardClient("k", 2026, transport=httpx.MockTransport(handler))
    client.seen = seen  # type: ignore[attr-defined]
    return client


class _Staff:
    def __init__(self, inst: StaffInstitution) -> None:
        self.inst = inst
        self.updates: list[dict[str, Any]] = []

    async def get_institution(self, institution_id: UUID) -> StaffInstitution | None:
        return self.inst if institution_id == self.inst.id else None

    async def update_institution(
        self, institution_id: UUID, values: dict[str, Any], *, expected_lock: int
    ) -> bool:
        self.updates.append(values)
        return True


def _inst(country: str = "US", domain: str | None = None) -> StaffInstitution:
    return StaffInstitution(
        id=new_id(),
        name="Harvard",
        name_local=None,
        country=country,
        city=None,
        website_domain=domain,
        kind="university",
        size_band=None,
        setting=None,
        languages=(),
        aliases=(),
        status="published",
        logo_url=None,
        cover_url=None,
        logo_zoom=1.0,
        logo_fit=None,
        created_at=NOW,
        updated_at=NOW,
        lock_version=3,
    )


class _Uow(FakeUow):
    def __init__(self, w: World, staff: _Staff) -> None:
        super().__init__(w.store)
        self.catalog_staff = staff  # type: ignore[assignment]
        self.applied: list[Any] = []
        outer = self

        class _Apply:
            async def apply_facts(
                self, iid: Any, facts: Any, rid: Any, now: Any
            ) -> None:
                outer.applied.append((iid, dict(facts), rid))

        self.catalog_proposals = _Apply()  # type: ignore[assignment]


def _svc(
    w: World, staff: _Staff, client: Any
) -> tuple[CatalogScorecardService, list[_Uow]]:
    made: list[_Uow] = []

    def factory() -> _Uow:
        made.append(_Uow(w, staff))
        return made[-1]

    can = CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW)).can_review
    return CatalogScorecardService(factory, client, can, FixedClock(NOW)), made


async def _ctx(w: World) -> AdmissionContext:
    return await w.ctx(STAFF, Role.COUNSELOR)


async def test_counselor_searches_by_name_and_unitid() -> None:
    w = World()
    svc, _ = _svc(w, _Staff(_inst()), _client())
    found = await svc.search(await _ctx(w), "Harvard")
    assert [s.unitid for s in found] == [166027]
    assert found[0].facts["acceptance_rate"] == {"min": 3.2, "max": 3.2}
    assert found[0].facts["intl_coa_usd"] == {"amount": 82866, "currency": "USD"}
    assert found[0].website_domain == "harvard.edu"
    assert [s.unitid for s in await svc.search(await _ctx(w), "166027")] == [166027]


async def test_attach_upserts_facts_sets_website_and_audits() -> None:
    w = World()
    inst = _inst()
    staff = _Staff(inst)
    svc, made = _svc(w, staff, _client())
    await svc.attach(await _ctx(w), inst.id, 166027)
    _, facts, _ = made[0].applied[0]
    assert set(facts) == {
        "acceptance_rate",
        "test_policy",
        "intl_tuition_usd",
        "intl_coa_usd",
    }
    assert facts["test_policy"]["value"] == "required"
    assert facts["acceptance_rate"]["year"] == NOW.year
    assert facts["acceptance_rate"]["source_url"].endswith("?166027")
    assert staff.updates == [{"website_domain": "harvard.edu"}]
    assert w.store.audit[-1].action == "catalog.scorecard_attached"


async def test_attach_keeps_existing_website_and_rejects_non_us() -> None:
    w = World()
    inst = _inst(domain="harvard.example")
    staff = _Staff(inst)
    svc, _ = _svc(w, staff, _client())
    await svc.attach(await _ctx(w), inst.id, 166027)
    assert staff.updates == []
    other = _Staff(replace(inst, country="GB"))
    svc2, _ = _svc(w, other, _client())
    with pytest.raises(ValidationFailedError):
        await svc2.attach(await _ctx(w), inst.id, 166027)


async def test_non_curator_is_refused_and_upstream_failure_surfaces() -> None:
    w = World()
    svc, _ = _svc(w, _Staff(_inst()), _client())
    with pytest.raises(AdmissionForbiddenError):
        await svc.search(await w.ctx(STUDENT, Role.STUDENT), "Harvard")
    broken, _ = _svc(w, _Staff(_inst()), _client(status=500))
    with pytest.raises(ScorecardUnavailableError):
        await broken.search(await _ctx(w), "Harvard")


async def test_client_sends_key_and_id_filter() -> None:
    client = _client()
    await client.get(166027)
    params = dict(client.seen[0].url.params)
    assert params["id"] == "166027" and params["api_key"] == "k"
    assert json.loads(json.dumps(params))
