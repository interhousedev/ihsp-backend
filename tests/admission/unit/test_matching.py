"""Preference tags, university tags, matching and status."""

from decimal import Decimal

from app.modules.admission.domain.admit_rate import admission_rate
from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.matching import (
    PreferenceAnswers,
    answers_from_stored,
    match,
    preference_tags,
    status_of,
    university_tags,
)
from app.shared.ids import new_id

FULL = PreferenceAnswers(
    experience="academic",
    setting=("city",),
    region=("US",),
    small_classes=True,
    ec_important=False,
    food_important=False,
    major="computer_science",
    prestige=True,
    academics_first=True,
    need_aid=True,
    budget="under_30k",
    cost_major=False,
)


def _inst(**kw: object) -> CatalogInstitution:
    base: dict[str, object] = {
        "id": new_id(),
        "slug": None,
        "name": "U",
        "country": "US",
        "city": "X",
        "status": "published",
    }
    base.update(kw)
    return CatalogInstitution(**base)  # type: ignore[arg-type]


def test_tags_empty_and_full() -> None:
    assert preference_tags(PreferenceAnswers()) == []
    assert not PreferenceAnswers().completed
    assert FULL.completed
    tags = preference_tags(FULL)
    assert "budget:under_30k" in tags and "setting:city" in tags
    assert "region:US" in tags and not any(t.startswith("distance") for t in tags)
    assert "experience:academic" in tags and "major:computer_science" in tags
    assert {"small_classes", "prestige", "academics_first", "aid_needed"} <= set(tags)
    assert "ec_important" not in tags and "cost_major" not in tags


def test_empty_lists_are_answers_without_tags_and_legacy_is_read() -> None:
    """ADM-U1-1: an empty list is answered (no filter); legacy shapes are read."""
    a = PreferenceAnswers(setting=(), region=(), need_aid=False)
    assert preference_tags(a) == [] and a.answered == 3
    legacy = answers_from_stored(
        {"setting": "city", "region": "any", "distance": "far", "budget": "any"}
    )
    assert legacy.setting == ("city",) and legacy.region == ()
    assert answers_from_stored({"region": "us"}).region == ("US",)


def test_any_listed_setting_or_country_meets_the_answer() -> None:
    """ADM-U1-2: an institution matches when its country is in the list."""
    pref = preference_tags(PreferenceAnswers(region=("GB", "US")))
    pct, ov = match(pref, university_tags(_inst()))
    assert pct == 100 and (ov.count, ov.total) == (1, 1)
    assert match(pref, university_tags(_inst(country="DE")))[0] == 0


def test_admission_rate_and_status() -> None:
    inst = _inst(facts={"acceptance_rate": FactView({"min": 10, "max": 20})})
    assert admission_rate(inst) == 0.15
    assert status_of(0.15) == "reach"
    assert status_of(0.3) == "target"
    assert status_of(0.7) == "safety"
    assert status_of(None) is None


def test_university_tags() -> None:
    inst = _inst(
        facts={
            "city_type": FactView("urban"),
            "fields": FactView(["Computer Science"]),
            "acceptance_rate": FactView({"min": 5, "max": 5}),
        },
        coa_total=Decimal(25000),
        coa_currency="USD",
        merit_available=True,
    )
    tags = set(university_tags(inst))
    assert {"setting:city", "region:US", "major:computer-science"} <= tags
    assert {"budget:under_30k", "prestige", "aid_needed"} <= tags
    assert "budget:under_10k" not in tags


def test_match_overlap() -> None:
    have = ["setting:city", "known:setting", "known:prestige"]
    pct, ov = match(["setting:city", "prestige"], have)
    assert pct == 50 and (ov.count, ov.total) == (1, 2)
    assert list(ov.tags) == ["setting:city"]
    assert match([], ["setting:city"])[0] == 0
    assert match(["small_classes"], ["setting:city"])[0] == 0


def test_missing_data_is_not_a_miss() -> None:
    bare = _inst()
    prefs = ["setting:city", "budget:under_30k", "prestige", "academics_first"]
    pct, ov = match(prefs, university_tags(bare))
    assert (pct, ov.total) == (0, 0)
    assert match(["budget:any", "region:US"], university_tags(bare))[0] == 100
    known = _inst(
        facts={
            "city_type": FactView("rural"),
            "acceptance_rate": FactView({"min": 50, "max": 50}),
        },
        coa_total=Decimal(40000),
        coa_currency="USD",
    )
    pct, ov = match(prefs, university_tags(known))
    assert (pct, ov.total) == (0, 4)


def test_admission_rate_prefers_international_and_survives_garbage() -> None:
    inst = _inst(
        facts={
            "intl_acceptance_rate": FactView({"min": "10", "max": 30}),
            "acceptance_rate": FactView({"min": 80, "max": 90}),
        }
    )
    assert admission_rate(inst) == 0.2
    bad = _inst(facts={"acceptance_rate": FactView({"min": "n/a", "max": None})})
    assert admission_rate(bad) is None
    assert admission_rate(_inst(facts={"acceptance_rate": FactView("x")})) is None


def test_seed_like_institution_matches_career_major_and_setting() -> None:
    """Regression: the discover list showed 0 for every university."""
    mit = _inst(
        country="US",
        facts={
            "fields": FactView(["Engineering", "Computer Science", "Natural sciences"]),
            "city_type": FactView("urban"),
            "institution_type": FactView("private"),
            "intl_coa_usd": FactView(82000),
        },
        coa_total=Decimal(82000),
        coa_currency="USD",
    )
    prefs = preference_tags(
        PreferenceAnswers(setting=("city",), major="computer_science", budget="any")
    )
    pct, ov = match(prefs, university_tags(mit))
    assert {"setting:city", "major:computer_science"} <= set(ov.tags)
    assert pct > 0 and ov.total >= 2

    bio = _inst(
        facts={
            "fields": FactView(["Business", "Economics"]),
            "city_type": FactView("urban"),
        }
    )
    _, ov = match(prefs, university_tags(bio))
    assert "major:computer_science" not in ov.tags and "setting:city" in ov.tags


def test_broad_fields_map_to_career_majors() -> None:
    eng = _inst(
        facts={"fields": FactView(["Engineering", "Natural sciences", "Business"])}
    )
    tags = set(university_tags(eng))
    assert {"major:mechanical_engineering", "major:physics", "major:business"} <= tags
    assert "major:law" not in tags
