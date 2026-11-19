"""Chooser domain: estimates as ranges, filters and affordability arithmetic."""

from decimal import Decimal

from app.modules.admission.domain.chooser import (
    CatalogFilters,
    CatalogInstitution,
    FactView,
    budget_upper,
    check_affordability,
    matches,
    needs_affordability_gate,
)
from app.modules.admission.domain.estimates import estimate
from app.shared.ids import new_id


def _inst(
    rate: tuple[int, int] | None = (40, 50),
    *,
    year: int | None = 2025,
    status: str = "published",
    **facts: FactView,
) -> CatalogInstitution:
    f = dict(facts)
    if rate:
        f["acceptance_rate"] = FactView({"min": rate[0], "max": rate[1]}, "u", year)
    return CatalogInstitution(new_id(), "x", "Xu", "US", "C", status, f)


def test_null_facts_give_unknown_without_range() -> None:
    e = estimate(_inst(None), "feasible", 2026)
    assert (e.label, e.low, e.high, e.missing) == (
        "unknown",
        None,
        None,
        ("acceptance_rate",),
    )


def test_unverified_institution_is_unknown() -> None:
    e = estimate(_inst(status="provisional"), "feasible", 2026)
    assert e.label == "unknown" and "unverified" in e.caveats


def test_range_target_and_stale_widening() -> None:
    fresh = estimate(_inst((40, 50)), "unknown", 2026)
    assert (fresh.low, fresh.high, fresh.label) == (35, 55, "target")
    stale = estimate(_inst((40, 50), year=2020), "unknown", 2026)
    assert (stale.low, stale.high) == (25, 65) and "stale" in stale.caveats


def test_low_rate_is_reach_and_capped() -> None:
    e = estimate(_inst((3, 5)), "feasible", 2026)
    assert e.label == "reach" and e.low == 1 and e.high <= 25
    assert "reach_for_everyone" in e.caveats


def test_safety_needs_feasible_cost() -> None:
    assert estimate(_inst((80, 90)), "feasible", 2026).label == "safety"
    assert estimate(_inst((80, 90)), "gap", 2026).label != "safety"


def test_filters_exclude_missing_facts() -> None:
    i = _inst(fields=FactView(["cs"], "u", 2025), city_type=FactView("urban"))
    assert matches(i, CatalogFilters(field="CS", city_type="urban", country="us"))
    assert not matches(i, CatalogFilters(city_type="rural"))
    assert not matches(i, CatalogFilters(max_crime_index=5))
    assert not matches(i, CatalogFilters(max_cost=Decimal(1000)))


def test_plan_filter_ed_matches_ed_and_ed2_only() -> None:
    """ADM-SEARCH-PLAN: the ED plan keeps ED/ED2 schools, drops REA/unknown."""
    ed = _inst(deadlines=FactView([{"plan": "ED2", "cycle": "2026-27"}], "u", 2025))
    harvard = _inst(deadlines=FactView([{"plan": "REA"}, {"plan": "RD"}], "u", 2025))
    ed_label = _inst(deadlines=FactView([{"plan": "Early Decision"}], "u", 2025))
    f = CatalogFilters(plan="ED")
    assert matches(ed, f) and matches(ed_label, f)
    assert not matches(harvard, f)
    assert not matches(_inst(), f)
    assert not matches(_inst(deadlines=FactView([{"plan": None}], "u", 2025)), f)
    assert matches(harvard, CatalogFilters(plan="REA"))


def test_budget_bands_and_gate() -> None:
    assert budget_upper("5k_15k") == 15000 and budget_upper("over_50k") is None
    assert check_affordability("under_5k", Decimal(60000)) == (
        "gap",
        Decimal(55000),
    )
    assert check_affordability("5k_15k", Decimal(10000))[0] == "feasible"
    assert check_affordability(None, Decimal(10000)) == ("unknown", None)
    assert check_affordability("5k_15k", None)[0] == "unknown"
    assert needs_affordability_gate("ED", "gap")
    assert not needs_affordability_gate("RD", "gap")
    assert not needs_affordability_gate("ED2", "signed_off")
