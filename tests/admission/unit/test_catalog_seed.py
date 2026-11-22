from app.modules.admission.infrastructure.catalog_data import (
    Institution,
    enrich_slugs,
    load_programs,
    load_seed,
)
from app.modules.admission.infrastructure.importers import ipeds, scorecard


def test_seed_validates_and_is_unique() -> None:
    seed = load_seed()
    assert len(seed) >= 30
    slugs = [i["slug"] for i in seed]
    assert len(slugs) == len(set(slugs))
    assert {"US", "GB", "DE", "KR", "JP", "TR", "MY", "AE", "IT", "HU"} <= {
        i["country"] for i in seed
    }
    for i in seed:
        facts = [i["test_policy"], i["intl_tuition_usd"], i["intl_coa_usd"]]
        facts += [i["aid"].get("basis"), i["acceptance_rate"]]
        for f in facts:
            if f and (f.get("value") is not None or f.get("min") is not None):
                assert f["source_url"], i["slug"]
        assert all(d["source_url"] for d in i["deadlines"]), i["slug"]
        if i["verified"]:
            assert any(facts) or i["deadlines"], i["slug"]


_CURRENCIES = {
    "USD",
    "EUR",
    "GBP",
    "KRW",
    "JPY",
    "TRY",
    "MYR",
    "AED",
    "HUF",
    "CAD",
    "KZT",
    "SGD",
    "UZS",
}


def test_every_value_has_source_and_year() -> None:
    enriched = enrich_slugs()
    for i in load_seed():
        slug = i["slug"]
        facts = [i["test_policy"], i["intl_tuition_usd"], i["intl_coa_usd"]]
        facts += list(i["aid"].values()) + [i["acceptance_rate"]]
        for f in facts:
            if f and (f.get("value") is not None or f.get("min") is not None):
                assert f["source_url"] and f["year"], slug
        for k in ("intl_tuition_usd", "intl_coa_usd"):
            if i[k]:
                assert i[k]["currency"] in _CURRENCIES, slug
        assert all(d["source_url"] for d in i["deadlines"]), slug
        if slug in enriched:  # enrichment entries may leave the profile unset
            continue
        assert i["city_type"] in {"urban", "suburban", "rural"}, slug
        assert i["institution_type"] in {"public", "private"}, slug


def test_unsourced_school_is_unverified() -> None:
    for i in load_seed():
        sourced = (
            any(
                f and (f.get("value") is not None or f.get("min") is not None)
                for f in [i["test_policy"], i["intl_tuition_usd"], i["intl_coa_usd"]]
                + list(i["aid"].values())
                + [i["acceptance_rate"]]
            )
            or i["deadlines"]
            or i["scholarships"]
        )
        if not sourced:
            assert not i["verified"], i["slug"]


def test_programs_load() -> None:
    programs = load_programs()
    assert programs
    assert all(p["url"] and p["year"] for p in programs)


def test_scorecard_parse() -> None:
    row = {
        "school.name": "Example University",
        "school.city": "Springfield",
        "school.state": "IL",
        "school.locale": "21",
        "school.school_url": "www.example.edu",
        "latest.admissions.admission_rate.overall": "0.0625",
        "latest.admissions.test_requirements": "1",
        "latest.cost.tuition.out_of_state": "50000",
        "latest.cost.attendance.academic_year": "NULL",
    }
    d = scorecard.parse_school(row, 2024)
    Institution.model_validate(d)
    assert d["city_type"] == "suburban"
    assert d["acceptance_rate"]["min"] in (6.2, 6.3)
    assert d["test_policy"]["value"] == "required"
    assert d["intl_coa_usd"] is None
    assert d["source_url"] == "https://www.example.edu"


def test_ipeds_parse() -> None:
    hd = [
        {
            "UNITID": "1",
            "INSTNM": "Sample College",
            "CITY": "Ithaca",
            "STABBR": "NY",
            "LOCALE": "33",
            "WEBADDR": "www.sample.edu",
        }
    ]
    adm = [{"UNITID": "1", "APPLCN": "1000", "ADMSSN": "250", "ADMCON7": "5"}]
    ic = [{"UNITID": "1", "TUITION3": "40000"}]
    (d,) = ipeds.parse_files(hd, adm, ic, 2023)
    Institution.model_validate(d)
    assert d["acceptance_rate"]["max"] == 25.0
    assert d["city_type"] == "rural"
    assert d["test_policy"]["value"] == "optional"
    assert d["source_url"] == "https://www.sample.edu"


def test_seed_focuses_are_verified_on_domain_and_loadable() -> None:
    from app.modules.admission.domain.focuses import on_domain
    from app.modules.admission.domain.intl_facts import clean_facts

    found = 0
    for i in load_seed():
        f = i.get("focuses")
        if not f:
            continue
        found += 1
        clean_facts(
            {"focuses": {**f, "source_url": f["value"][0]["source_url"], "year": 2026}}
        )
        assert all(
            on_domain(x["source_url"], i.get("website_domain")) for x in f["value"]
        )
    assert found >= 2
