"""Catalog proposals with international facts: limits, duplicates, outputs."""

from typing import Any

from app.interfaces.http.v1.admission.routes_chooser import InstitutionOut
from app.interfaces.http.v1.admission.schemas_catalog_staff import (
    CatalogProposalOut,
    FactSpecOut,
)
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    CatalogDuplicateError,
    CatalogFactInvalidError,
    CatalogProposalLimitError,
    InvalidProofUrlError,
)
from app.modules.admission.domain.intl_fact_display import fact_spec_view
from app.shared.actor import Role
from app.shared.base_error import RateLimitedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, STUDENT, World, _assign
from tests.fakes.clock import FixedClock

import pytest

URL = "https://example.edu/admissions"
FACT = {"value": 12.5, "source_url": URL, "year": 2025, "note": None}


class _Limiter:
    def __init__(self) -> None:
        self.hits = 0

    async def hit(self, key: str, *, limit: int, window_seconds: int) -> int:
        self.hits += 1
        if self.hits > limit:
            raise RateLimitedError(params={"retry_after": 5})
        return self.hits


def _svc(w: World, limiter: Any = None, per_day: int = 100) -> CatalogProposalService:
    return CatalogProposalService(
        lambda: FakeUow(w.store), FixedClock(NOW), limiter, per_day
    )


async def _curator(w: World) -> AdmissionContext:
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    return await w.ctx(STAFF, Role.COUNSELOR)


async def _propose(
    w: World,
    ctx: AdmissionContext,
    svc: CatalogProposalService | None = None,
    **kw: Any,
) -> Any:
    args: dict[str, Any] = {
        "kind": "institution",
        "target_id": None,
        "fields": {"name": "Test University", "country": "GB"},
        "source_url": URL,
        "note": None,
    } | kw
    return await (svc or _svc(w)).propose(ctx, **args)


async def test_facts_are_kept_apart_from_fields() -> None:
    """ADM-INTL-1: facts live on the proposal, never inside the field payload."""
    w = World()
    ctx = await _curator(w)
    p = await _propose(w, ctx, facts={"acceptance_rate": FACT})
    assert "facts" not in p.payload
    assert p.facts["acceptance_rate"]["year"] == 2025
    assert w.store.proposals[p.id].facts == p.facts


async def test_facts_on_a_scholarship_are_rejected() -> None:
    """ADM-INTL-2: only institutions carry facts."""
    w = World()
    ctx = await _curator(w)
    with pytest.raises(CatalogFactInvalidError) as e:
        await _propose(
            w,
            ctx,
            kind="scholarship",
            fields={"name": "Grant", "basis": "merit"},
            facts={"acceptance_rate": FACT},
        )
    assert e.value.params["reason"] == "kind"


async def test_facts_only_edit_of_an_existing_institution() -> None:
    """ADM-INTL-3: an edit may carry facts and no fields."""
    w = World()
    ctx = await _curator(w)
    target = new_id()
    w.store.known_targets.add(target)
    p = await _propose(
        w, ctx, target_id=target, fields={}, facts={"acceptance_rate": FACT}
    )
    assert p.payload == {} and p.target_id == target


@pytest.mark.parametrize(
    "key", ["test university", "tu", "example.edu"], ids=["name", "alias", "domain"]
)
async def test_duplicate_institution_is_rejected(key: str) -> None:
    """ADM-INTL-4: a name, alias or domain of a known school is a duplicate."""
    w = World()
    ctx = await _curator(w)
    known = new_id()
    w.store.institution_names[key] = known
    with pytest.raises(CatalogDuplicateError) as e:
        await _propose(
            w,
            ctx,
            fields={
                "name": "Test University",
                "country": "GB",
                "aliases": ["TU"],
                "website_domain": "example.edu",
            },
        )
    assert e.value.params == {"institution_id": str(known)}


async def test_pending_create_is_a_duplicate() -> None:
    """ADM-INTL-5: a second pending create with the same name names the first."""
    w = World()
    ctx = await _curator(w)
    first = await _propose(w, ctx)
    with pytest.raises(CatalogDuplicateError) as e:
        await _propose(w, ctx, fields={"name": "TEST university", "country": "GB"})
    assert e.value.params == {"proposal_id": str(first.id)}


async def test_proposal_rate_limit_carries_the_limit() -> None:
    """ADM-INTL-6: the proposal after the daily limit fails with the limit."""
    w = World()
    ctx = await _curator(w)
    svc = _svc(w, _Limiter(), per_day=1)
    await _propose(w, ctx, svc, fields={"name": "A", "country": "GB"})
    with pytest.raises(CatalogProposalLimitError) as e:
        await _propose(w, ctx, svc, fields={"name": "B", "country": "GB"})
    assert e.value.params["limit"] == 1


async def test_proposal_is_audited() -> None:
    """ADM-INTL-7: creating a proposal emits catalog.proposal_created."""
    w = World()
    ctx = await _curator(w)
    await _propose(w, ctx)
    assert "catalog.proposal_created" in [a.action for a in w.store.audit]


async def test_student_may_not_read_the_fact_spec() -> None:
    """ADM-INTL-8: the fact-spec check is for proposers only."""
    w = World()
    svc = _svc(w)
    svc.require_proposer(await _curator(w))
    with pytest.raises(AdmissionForbiddenError):
        svc.require_proposer(await w.ctx(STUDENT, Role.STUDENT))


def test_fact_spec_output_shape() -> None:
    """ADM-INTL-9: the registry validates as the fact-spec response."""
    out = FactSpecOut.model_validate({"groups": fact_spec_view("ru")})
    assert out.groups and all(g.label and g.facts for g in out.groups)


def _institution() -> CatalogInstitution:
    return CatalogInstitution(
        id=new_id(),
        slug=None,
        name="Test University",
        country="GB",
        city=None,
        status="published",
        facts={
            "acceptance_rate": FactView(
                value=12.5,
                source_url=URL,
                year=2025,
                note=None,
                verified=True,
                unit="percent",
            )
        },
    )


def test_detail_output_only_on_the_detail_view() -> None:
    """ADM-INTL-10: details and factors fill in the detail view only."""
    inst = _institution()
    assert InstitutionOut.of(inst).details == []
    assert InstitutionOut.of(inst).factors == []
    detail = InstitutionOut.of(inst, "en", detail=True)
    assert [r.key for g in detail.details for r in g.rows] == ["acceptance_rate"]


async def test_proposal_out_maps_facts() -> None:
    """ADM-INTL-11: the stored proposal output lists its facts."""
    w = World()
    ctx = await _curator(w)
    p = await _propose(w, ctx, facts={"acceptance_rate": FACT})
    out = CatalogProposalOut.of(p)
    assert out.facts["acceptance_rate"].year == 2025


@pytest.mark.parametrize(
    "url",
    ["https://harvard.edu@evil.example/", "https://user:pw@harvard.edu/"],
)
async def test_proposal_source_url_rejects_userinfo(url: str) -> None:
    """ADM-INTL-SEC-2: the proposal-level proof URL may not carry userinfo."""
    w = World()
    ctx = await _curator(w)
    with pytest.raises(InvalidProofUrlError):
        await _propose(w, ctx, source_url=url)


async def test_rejected_proposals_do_not_burn_the_daily_quota() -> None:
    """ADM-INTL-SEC-3: only a proposal that is stored counts against the limit."""
    w = World()
    ctx = await _curator(w)
    w.store.institution_names["dup"] = new_id()
    svc = _svc(w, _Limiter(), per_day=1)
    bad = {"acceptance_rate": FACT | {"value": 500}}
    with pytest.raises(CatalogFactInvalidError):
        await _propose(w, ctx, svc, facts=bad)
    with pytest.raises(CatalogDuplicateError):
        await _propose(w, ctx, svc, fields={"name": "Dup", "country": "GB"})
    first = await _propose(w, ctx, svc, fields={"name": "A", "country": "GB"})
    assert first.id in w.store.proposals
    with pytest.raises(CatalogProposalLimitError):
        await _propose(w, ctx, svc, fields={"name": "B", "country": "GB"})


async def test_proposal_text_fields_are_folded_before_storing() -> None:
    """ADM-INTL-SEC-4: name and aliases are stored trimmed, single-spaced."""
    w = World()
    ctx = await _curator(w)
    p = await _propose(
        w,
        ctx,
        fields={
            "name": "  Foo   Bar ",
            "country": "GB",
            "aliases": ["  A  B ", "  "],
        },
    )
    stored = w.store.proposals[p.id].payload
    assert stored["name"] == "Foo Bar"
    assert stored["aliases"] == ["A B"]
