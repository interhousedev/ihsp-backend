"""Catalog agent rehearsal fixes: paging, deadlines, country, scope, prompts."""

import dataclasses
from types import SimpleNamespace
from typing import Any

from app.interfaces.http.dependencies import _personal_token_scope
from app.interfaces.http.v1.admission.routes_catalog_staff import (
    list_catalog_proposals,
)
from app.interfaces.http.v1.admission.routes_chooser import InstitutionOut
from app.interfaces.http.v1.admission.schemas_catalog_staff import (
    CatalogProposalIn,
    CatalogProposalOut,
    FactSpecOut,
)
from app.modules.admission.application.catalog_proposals import (
    CatalogProposalService,
)
from app.modules.admission.application.chooser import CatalogService
from app.modules.admission.domain.chooser import CatalogFilters, FactView
from app.modules.admission.domain.intl_fact_display import (
    OPTION_LABELS,
    fact_spec_view,
)
from app.modules.admission.domain.intl_facts import FACT_SPECS
from app.modules.identity.domain.personal_token import PersonalTokenScope
from app.shared.actor import Actor, Role
from app.shared.base_error import ValidationFailedError
from app.shared.ids import new_id
from tests.admission.unit.fakes import NOW, FakeUow
from tests.admission.unit.test_access_policy import STAFF, World, _assign
from tests.admission.unit.test_catalog_search import _inst
from tests.fakes.clock import FixedClock

import pytest
from fastapi import Request

URL = "https://example.edu/admissions"
PROMPT = {
    "cycle": "2025-26",
    "prompt": "Why this college?",
    "word_limit": 250,
    "required": True,
    "source_url": URL,
}


def _catalog(w: World, n: int) -> CatalogService:
    for i in range(n):
        inst = _inst(name=f"Uni {i:03d}", country="DE" if i % 2 else "US")
        w.store.institutions[inst.id] = inst
    return CatalogService(lambda: FakeUow(w.store))


async def test_limit_50_and_second_page_serialise() -> None:
    """ADM-CAT-API-1: the largest page and the next one map to the API shape."""
    w = World()
    svc = _catalog(w, 70)
    first = await svc.search(CatalogFilters(), cursor=0, limit=50)
    second = await svc.search(CatalogFilters(), cursor=50, limit=50)
    assert len(first.items) == 50 and first.next_cursor == 50
    assert len(second.items) == 20 and second.next_cursor is None
    for page in (first, second):
        assert len([InstitutionOut.of(i) for i in page.items]) == len(page.items)


def test_a_deadline_without_a_date_is_not_a_500() -> None:
    """ADM-CAT-API-1: a seeded deadline with no date no longer breaks the page."""
    rows = [
        {"plan": "RD", "date": None, "cycle": "2026-27"},
        {"plan": "ED", "date": "2026-11-01", "cycle": "2026-27"},
    ]
    out = InstitutionOut.of(_inst(deadlines=rows))
    assert [d.plan for d in out.deadlines] == ["ED"]


async def test_country_filter_matches_any_case() -> None:
    """ADM-CAT-API-2: `country=de` and `DE` both list the German institutions."""
    w = World()
    svc = _catalog(w, 10)
    odd = dataclasses.replace(_inst(name="Heidelberg", country="de"))
    w.store.institutions[odd.id] = odd
    for code in ("DE", "de"):
        page = await svc.search(CatalogFilters(country=code), limit=50)
        names = {i.name for i in page.items}
        assert "Heidelberg" in names
        assert len(page.items) == 6


async def _scoped(w: World, scopes: frozenset[str]) -> Any:
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    ctx = await w.ctx(STAFF, Role.COUNSELOR)
    actor = Actor(STAFF, frozenset({Role.COUNSELOR}), scopes=scopes)
    return dataclasses.replace(ctx, actor=actor)


async def test_catalog_token_cannot_review() -> None:
    """ADM-CAT-API-3: `can_review` is false for an admission:catalog token."""
    w = World()
    svc = CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW))
    container = SimpleNamespace(
        admission=SimpleNamespace(catalog_proposals=svc),
    )
    plain = await list_catalog_proposals(container, await _scoped(w, frozenset()))
    token = await list_catalog_proposals(
        container, await _scoped(w, frozenset({"admission:catalog"}))
    )
    assert plain.can_review is True
    assert token.can_review is False


def _scope(method: str, path: str) -> PersonalTokenScope | None:
    request = Request({"type": "http", "method": method, "path": path, "headers": []})
    return _personal_token_scope(request)


_ID = "0191d7a2-1b2c-7d3e-8f40-123456789abc"
_STAFF = "/v1/admission/staff"


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", f"{_STAFF}/catalog/proposals/{_ID}/review"),
        ("POST", f"{_STAFF}/catalog/proposals/{_ID}/approve"),
        ("POST", f"{_STAFF}/catalog/proposals/{_ID}/reject"),
        ("POST", f"{_STAFF}/catalog/proposals/{_ID}/apply"),
        ("GET", f"{_STAFF}/catalog/proposals/{_ID}"),
        ("PUT", f"{_STAFF}/catalog/proposals"),
        ("DELETE", f"{_STAFF}/catalog/proposals"),
        ("GET", f"{_STAFF}/catalog/proposals/"),
        ("GET", f"{_STAFF}/catalog/proposalsX"),
        ("PATCH", f"{_STAFF}/catalog/institutions/{_ID}"),
        ("PUT", f"{_STAFF}/catalog/institutions/{_ID}/supp-prompts/2025-26"),
        ("POST", f"{_STAFF}/exemplars/{_ID}/publish"),
        ("GET", f"{_STAFF}/students"),
        ("POST", f"{_STAFF}/assignments"),
        ("POST", "/v1/admission/catalog/institutions"),
    ],
)
def test_catalog_token_is_refused_outside_its_list(method: str, path: str) -> None:
    """ADM-CAT-API-3: the allowlist is a full match; no review or write slips by."""
    assert _scope(method, path) is None


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", f"{_STAFF}/catalog/proposals"),
        ("POST", f"{_STAFF}/catalog/proposals"),
        ("GET", f"{_STAFF}/catalog/fact-spec"),
        ("GET", "/v1/admission/catalog/institutions"),
    ],
)
def test_catalog_token_keeps_its_routes(method: str, path: str) -> None:
    """ADM-CAT-API-3: the listed routes still map to the catalog scope."""
    assert _scope(method, path) is PersonalTokenScope.ADMISSION_CATALOG


async def _curator(w: World) -> Any:
    w.store.assignments[STAFF] = (_assign("counselor_full", "all", None),)
    return await w.ctx(STAFF, Role.COUNSELOR)


def _svc(w: World) -> CatalogProposalService:
    return CatalogProposalService(lambda: FakeUow(w.store), FixedClock(NOW))


async def test_proposal_carries_prompts_and_applies_them() -> None:
    """ADM-CAT-API-4: approval writes the prompts like the staff PUT does."""
    w = World()
    ctx = await _curator(w)
    target = new_id()
    w.store.known_targets.add(target)
    svc = _svc(w)
    created = await svc.propose(
        ctx,
        kind="institution",
        target_id=target,
        fields={},
        source_url=URL,
        note=None,
        supp_prompts=[PROMPT, {**PROMPT, "prompt": " Second ", "word_limit": None}],
    )
    out = CatalogProposalOut.of(created)
    assert [p.prompt for p in out.supp_prompts] == ["Why this college?", "Second"]
    assert "supp_prompts" not in created.payload

    await svc.review(ctx, created.id, approve=True, note=None, lock_version=0)

    stored = w.store.supp_prompts[target]["2025-26"]
    assert [(p.position, p.prompt, p.word_limit) for p in stored] == [
        (0, "Why this college?", 250),
        (1, "Second", None),
    ]


async def test_rejected_proposal_writes_no_prompts() -> None:
    """ADM-CAT-API-4: rejecting a proposal leaves the prompts unwritten."""
    w = World()
    ctx = await _curator(w)
    target = new_id()
    w.store.known_targets.add(target)
    svc = _svc(w)
    p = await svc.propose(
        ctx,
        kind="institution",
        target_id=target,
        fields={},
        source_url=URL,
        note=None,
        supp_prompts=[PROMPT],
    )
    await svc.review(ctx, p.id, approve=False, note="no", lock_version=0)
    assert w.store.supp_prompts == {}


@pytest.mark.parametrize(
    ("items", "field"),
    [
        ([{**PROMPT, "prompt": "  "}], "prompt"),
        ([{**PROMPT, "word_limit": 0}], "word_limit"),
        ([{**PROMPT, "source_url": "http://example.edu"}], "source_url"),
        ([{**PROMPT, "source_url": None}], "source_url"),
        ([PROMPT] * 13, "supp_prompts"),
    ],
)
async def test_invalid_proposed_prompts_are_refused(
    items: list[dict[str, Any]], field: str
) -> None:
    """ADM-CAT-API-4: the same checks as the staff PUT, plus a mandatory source."""
    w = World()
    ctx = await _curator(w)
    with pytest.raises(ValidationFailedError) as caught:
        await _svc(w).propose(
            ctx,
            kind="institution",
            target_id=new_id(),
            fields={},
            source_url=URL,
            note=None,
            supp_prompts=items,
        )
    assert caught.value.params["field"] == field


async def test_prompts_only_on_institutions() -> None:
    """ADM-CAT-API-4: a scholarship proposal cannot carry prompts."""
    w = World()
    ctx = await _curator(w)
    with pytest.raises(ValidationFailedError):
        await _svc(w).propose(
            ctx,
            kind="scholarship",
            target_id=None,
            fields={"name": "G", "provider": "government", "basis": "merit"},
            source_url=URL,
            note=None,
            supp_prompts=[PROMPT],
        )


def test_proposal_input_types_prompts_and_fields() -> None:
    """ADM-CAT-API-4: the schema caps the list at 12 and requires https."""
    ok = CatalogProposalIn.model_validate(
        {
            "kind": "institution",
            "fields": {"name": "X", "country": "gb", "unknown": 1},
            "supp_prompts": [PROMPT],
            "source_url": URL,
        }
    )
    assert ok.fields.model_dump(exclude_none=True) == {"name": "X", "country": "gb"}
    for bad in ([PROMPT] * 13, [{**PROMPT, "source_url": "http://x.edu"}]):
        with pytest.raises(ValueError):
            CatalogProposalIn.model_validate(
                {"kind": "institution", "supp_prompts": bad, "source_url": URL}
            )


async def test_country_is_stored_upper_case() -> None:
    """ADM-CAT-API-2: a proposed `de` is stored as `DE`."""
    w = World()
    ctx = await _curator(w)
    p = await _svc(w).propose(
        ctx,
        kind="institution",
        target_id=None,
        fields={"name": "Test University", "country": "de"},
        source_url=URL,
        note=None,
    )
    assert p.payload["country"] == "DE"


def test_ouac_is_an_application_platform_with_labels() -> None:
    """ADM-CAT-API-5: OUAC is an option with a label in every locale."""
    assert "ouac" in FACT_SPECS["application_platforms"].options
    assert OPTION_LABELS["application_platforms"]["ouac"] == ("OUAC",) * 3


def test_fact_spec_states_shape_and_example_of_each_fact() -> None:
    """ADM-CAT-API-6: every fact says what its value looks like, with a sample."""
    view = FactSpecOut.model_validate({"groups": fact_spec_view("en")})
    facts = {f.key: f for g in view.groups for f in g.facts}
    assert set(facts) <= set(FACT_SPECS)
    assert all(f.value_shape for f in facts.values())
    money = next(f for f in facts.values() if f.kind == "money")
    assert set(money.example) == {"amount", "currency"}
    assert "amount" in money.value_shape
    ranges = [f for f in facts.values() if f.kind == "range"]
    assert ranges and all(set(f.example) == {"min", "max"} for f in ranges)
    assert FACT_SPECS["deadlines"].kind == "deadlines"


def test_every_example_passes_fact_validation() -> None:
    """ADM-CAT-API-6: sample values pass the same validation as input."""
    from app.modules.admission.domain.intl_fact_display import _example
    from app.modules.admission.domain.intl_facts import clean_fact

    for spec in FACT_SPECS.values():
        clean_fact(spec.key, _example(spec), source_url=URL, year=2025)


def test_inst_helper_keeps_fact_views() -> None:
    """ADM-CAT-API-1: the helper builds facts as the catalog does."""
    assert isinstance(_inst(x=1).facts["x"], FactView)
