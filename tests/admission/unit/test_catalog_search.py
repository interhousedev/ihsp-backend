"""Catalog: study-field taxonomy, deadline cleanup, filters, ranking, logos."""

import dataclasses
import datetime as dt
from typing import Any

from app.modules.admission.domain.catalog_display import (
    clean_deadlines,
    default_logo_fit,
    highlights,
    resolve_logo_fit,
    valid_logo_zoom,
)
from app.modules.admission.domain.chooser import (
    CatalogFilters,
    CatalogInstitution,
    FactView,
    cycle_of,
    matches,
    rank_hits,
)
from app.modules.admission.domain.study_fields import (
    build_taxonomy,
    canonical_id,
    canonical_names,
)
from app.shared.ids import new_id


def _inst(
    name: str = "Xu", country: str = "US", city: str = "C", **facts: Any
) -> CatalogInstitution:
    f = {k: FactView(v, "u", 2025, None, True) for k, v in facts.items()}
    return CatalogInstitution(new_id(), "x", name, country, city, "published", f)


def test_taxonomy_merges_spellings() -> None:
    ids = {canonical_id(n) for n in ("Computer Science", "Computer Sciences")}
    assert len(ids) == 1
    assert canonical_id("Taxation") == canonical_id("Tax Law/Taxation")
    assert len(canonical_names(["Computer Science", "computer science"])) == 1


def test_taxonomy_groups_have_stable_ids_and_labels() -> None:
    a = build_taxonomy(["Computer Science", "Underwater Basketry"], "ru")
    b = build_taxonomy(["Underwater Basketry", "Computer Science"], "ru")
    assert a == b
    items = [i for g in a for i in g["items"]]
    assert len({i["id"] for i in items}) == len(items)
    assert all(g["label"] and g["items"] for g in a)
    assert any(i["id"].startswith("x_") for i in items)


def test_deadline_notes_never_leak() -> None:
    raw = [
        {
            "plan": "RD",
            "date": "2027-01-05",
            "cycle": "2026-27",
            "note": "Page prints no year; treated as 2026-27",
        }
    ]
    out = clean_deadlines(raw, "en")
    assert out[0]["plan"] == "RD" and out[0]["date"] == dt.date(2027, 1, 5)
    assert "treated" not in repr(out) and "note" not in out[0]


def test_deadline_notify_by_from_note() -> None:
    raw = [{"plan": "ED", "date": "2026-11-01", "note": "Notified by Dec 15"}]
    out = clean_deadlines(raw, "en")
    assert out[0]["notify_by"] == dt.date(2026, 12, 15)


def test_highlights_localized_and_skip_missing() -> None:
    inst = _inst(institution_type="university", test_policy="test_optional")
    en = highlights(inst, "en")
    ru = highlights(inst, "ru")
    assert {h["key"] for h in en} >= {"institution_type", "test_policy"}
    assert en != ru and all(h["value_text"] for h in en)


def test_filters_institution_type_policy_plan_cycle() -> None:
    inst = _inst(
        institution_type="liberal_arts",
        test_policy="test_blind",
        deadlines=[{"plan": "ED", "date": "2026-11-01", "cycle": "2026-27"}],
    )
    assert matches(inst, CatalogFilters(institution_type="liberal_arts"))
    assert not matches(inst, CatalogFilters(institution_type="research"))
    assert matches(inst, CatalogFilters(test_policy="test_blind"))
    assert not matches(inst, CatalogFilters(test_policy="required"))
    assert matches(inst, CatalogFilters(plan="ED", cycle="2026-27"))
    assert not matches(inst, CatalogFilters(plan="EA"))
    assert not matches(inst, CatalogFilters(cycle="2027-28"))


def test_field_filter_uses_canonical_ids() -> None:
    inst = _inst(fields=["Computer Science & AI"])
    assert matches(inst, CatalogFilters(field="Computer Sciences"))


def test_search_ranks_name_before_city() -> None:
    by_city = _inst("Zed College", city="Boston")
    by_name = _inst("Boston University", city="Boston")
    alias = dataclasses.replace(_inst("MIT Ltd"), aliases=("Boston Tech",))
    hits = [
        i for i in (by_city, alias, by_name) if matches(i, CatalogFilters(q="boston"))
    ]
    ranked = rank_hits(hits, "boston")
    assert ranked[0] is by_name and ranked[-1] is by_city


def test_logo_fit_and_zoom() -> None:
    assert default_logo_fit(3.0) == "contain"
    assert default_logo_fit(1.0) == "circle"
    assert resolve_logo_fit("circle", 3.0) == "circle"
    assert resolve_logo_fit(None, 3.0) == "contain"
    assert valid_logo_zoom(3.0) and not valid_logo_zoom(3.1)


def test_cycle_of_starts_in_august() -> None:
    assert cycle_of(dt.date(2026, 8, 1)) == "2026-27"
    assert cycle_of(dt.date(2027, 3, 1)) == "2026-27"
