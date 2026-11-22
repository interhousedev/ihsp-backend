"""Ranking subjects, relevant rankings, experience meters, map links, MatchOut."""

import datetime as dt
from decimal import Decimal

from app.interfaces.http.v1.admission.routes_matching import MatchOut
from app.modules.admission.application.matching import MatchItem
from app.modules.admission.domain.chooser import (
    AidProfile,
    CatalogInstitution,
    FactView,
)
from app.modules.admission.domain.errors import CatalogFactInvalidError
from app.modules.admission.domain.intl_facts import clean_facts
from app.modules.admission.domain.matching import Overlap
from app.modules.admission.domain.rankings import (
    DEFAULT_MAPS_TEMPLATE,
    experience_meters,
    map_url,
    relevant_rankings,
    subjects_for,
    valid_maps_template,
)
from app.shared.ids import new_id

import pytest

RANKS = [
    {
        "system": "the",
        "subject": "business",
        "rank": 40,
        "year": 2026,
        "source_url": "u",
    },
    {
        "system": "qs",
        "subject": "business",
        "rank": 55,
        "year": 2026,
        "source_url": "u",
    },
    {"system": "qs", "subject": "overall", "rank": 3, "year": 2026, "source_url": "u"},
    {"system": "qs", "subject": "law", "rank": 9, "year": 2026, "source_url": "u"},
]


def test_subjects_follow_fields_in_order() -> None:
    assert subjects_for(["computer_science", "business"]) == (
        "computer_science",
        "business",
    )
    assert subjects_for(["data_science"]) == ("computer_science", "mathematics")
    assert subjects_for(["unknown_field"]) == ()


def test_rankings_are_relevant_only_best_system_first_max_two() -> None:
    out = relevant_rankings(RANKS, ["computer_science", "business", "law", "x"])
    assert [(r["subject"], r["system"]) for r in out] == [
        ("business", "qs"),
        ("law", "qs"),
    ]
    assert len(relevant_rankings(RANKS, ["business", "law", "law"], limit=1)) == 1
    both = relevant_rankings(RANKS, ["law", "business"])
    assert [r["subject"] for r in both] == ["law", "business"]
    assert relevant_rankings(RANKS, ["overall"]) == []
    assert relevant_rankings(None, ["business"]) == []


def test_experience_meters_skip_missing_and_pick_locale() -> None:
    value = {
        "social": 4,
        "work": 9,
        "notes": {"social": {"en": "Clubs", "ru": "Клубы"}},
    }
    assert experience_meters(value, "ru") == [
        {"key": "social", "score": 4, "note": "Клубы"}
    ]
    assert experience_meters(value, "uz")[0]["note"] == "Clubs"


def test_map_url_default_override_and_template() -> None:
    url = map_url("MIT", "Cambridge, MA", "US")
    assert url == DEFAULT_MAPS_TEMPLATE.replace(
        "{query}", "MIT%2C+Cambridge%2C+MA%2C+US"
    )
    assert (
        map_url("MIT", None, "US", override="https://m.example/x")
        == "https://m.example/x"
    )
    tpl = "https://maps.example/?q={query}"
    assert map_url("A", None, "US", template=tpl) == "https://maps.example/?q=A%2C+US"
    assert map_url("A", None, "US", template="http://bad/{query}").startswith(
        "https://www.google"
    )
    assert valid_maps_template(tpl) and not valid_maps_template("https://x/")


def test_new_fact_kinds_validate() -> None:
    src = {"source_url": "https://x.org", "year": 2026}
    ok = clean_facts(
        {
            "experience_scores": {"value": {"social": 5, "research": 3}, **src},
            "map_url": {"value": "https://maps.example/p", **src},
        }
    )
    assert ok["experience_scores"].value == {"social": 5, "research": 3}
    for key, bad in (
        ("experience_scores", {"social": 6}),
        ("map_url", "http://x"),
        ("rankings", [{"system": "foo", "subject": "law", "rank": 1, "year": 2026}]),
    ):
        with pytest.raises(CatalogFactInvalidError):
            clean_facts({key: {"value": bad, **src}})


def _inst() -> CatalogInstitution:
    fv = lambda v: FactView(v, "https://x.org", 2026, None, False)  # noqa: E731
    return CatalogInstitution(
        id=new_id(),
        slug=None,
        name="Uni",
        country="GB",
        city="Leeds",
        status="published",
        facts={
            "fields": fv(["Business"]),
            "rankings": fv(RANKS),
            "experience_scores": fv({"research": 5}),
        },
        coa_total=Decimal(50000),
        coa_currency="USD",
        aid_profile=AidProfile(avg_aid=Decimal(12000), avg_aid_scope="intl"),
        description={"en": "English", "ru": "Русский"},
    )


def test_match_out_maps_card_details() -> None:
    m = MatchItem(_inst(), 80, Overlap(0, 0, ()), None, Decimal(50000), None)
    out = MatchOut.of(m, today=dt.date(2026, 1, 1), locale="ru", subjects=("business",))
    assert out.description == "Русский"
    assert [r.system for r in out.rankings] == ["qs"]
    assert (out.cost_usd, out.net_cost_usd, out.aid_estimate_usd) == (
        50000,
        38000,
        12000,
    )
    assert [(e.key, e.score) for e in out.experience] == [("research", 5)]
    assert "Uni%2C+Leeds%2C+GB" in out.map_url
    bare = MatchOut.of(m, today=dt.date(2026, 1, 1), subjects=())
    assert bare.rankings == []
