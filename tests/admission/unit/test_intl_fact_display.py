"""ADM-INTL: localised view of the fact registry and of a school's facts."""

from typing import Any

from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.intl_fact_display import (
    detail_groups,
    fact_spec_view,
    importance_factors,
)
from app.modules.admission.domain.intl_facts import FACT_GROUPS, FACT_SPECS
from app.shared.ids import new_id


def inst(**facts: Any) -> CatalogInstitution:
    f = {
        k: v if isinstance(v, FactView) else FactView(v, "https://x.edu", 2026, "n")
        for k, v in facts.items()
    }
    return CatalogInstitution(new_id(), "x", "X", "US", None, "published", f)


def rows(groups: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {r["key"]: r for g in groups for r in g["rows"]}


def test_spec_view_complete_and_localised() -> None:
    """ADM-INTL-9: all groups and keys, labels translated in ru and uz."""
    for locale in ("en", "ru", "uz"):
        view = fact_spec_view(locale)
        assert [g["key"] for g in view] == list(FACT_GROUPS)
        facts = {f["key"]: f for g in view for f in g["facts"]}
        assert set(facts) == set(FACT_SPECS)
        for g in view:
            assert g["label"]
        for key, f in facts.items():
            assert f["label"]
            if locale != "en":
                assert f["label"] != key
            for p in f["parts"]:
                assert p["label"]
            assert [o["value"] for o in f["options"]] == list(FACT_SPECS[key].options)
    en = {f["key"]: f for g in fact_spec_view("en") for f in g["facts"]}
    assert en["english_tests"]["parts"][0] == {
        "key": "toefl_ibt",
        "label": "TOEFL iBT",
        "min": 0,
        "max": 120,
        "step": 1,
    }
    assert en["test_policy"]["options"][0]["label"] == "Tests required"
    assert en["admission_factors"]["options"][0]["label"] == "Very important"
    assert en["intl_tuition_usd"]["unit"] == "USD"


def test_detail_groups_skip_and_text() -> None:
    """ADM-INTL-10: missing and excluded facts skipped; texts are human."""
    got = detail_groups(
        inst(
            city_type="urban",
            fields=["Biology"],
            deadlines=[{"plan": "ED"}],
            admission_factors={"gpa": "important"},
            intl_tuition_usd=FactView(60000, "https://x.edu", 2026, None, True, "USD"),
            intl_coa_usd=FactView(25000, "https://x.edu", 2026, None, True, "GBP"),
            acceptance_rate=FactView(
                {"min": 4, "max": 6}, None, None, None, True, "percent"
            ),
            sat_mid50={"min": 1450, "max": 1560},
            english_tests={"toefl_ibt": 100, "ielts": 7},
            aid_forms=["fafsa", "idoc"],
            loan_free=True,
            meets_full_need=False,
            intl_aid_deadline="2026-02-01",
            test_policy=None,
        ),
        "en",
    )
    r = rows(got)
    assert not {"fields", "deadlines", "admission_factors", "test_policy"} & set(r)
    assert [g["key"] for g in got] == ["overview", "selectivity", "costs", "english"]
    assert r["city_type"]["value_text"] == "Urban"
    assert r["intl_tuition_usd"]["value_text"] == "$60 000"
    assert r["intl_tuition_usd"]["value"] == 60000
    assert r["intl_coa_usd"]["value_text"] == "GBP 25 000"
    assert r["acceptance_rate"]["value_text"] == "4-6%"
    assert r["sat_mid50"]["value_text"] == "1450-1560"
    assert r["english_tests"]["value_text"] == "TOEFL iBT 100 · IELTS 7"
    assert r["aid_forms"]["value_text"] == "FAFSA, IDOC"
    assert r["loan_free"]["value_text"] == "Yes"
    assert r["meets_full_need"]["value_text"] == "No"
    assert r["intl_aid_deadline"]["value_text"] == "1 Feb 2026"
    assert r["city_type"]["source_url"] == "https://x.edu"
    assert r["city_type"]["year"] == 2026
    assert all("note" not in row for row in r.values())
    assert [
        x["value_text"]
        for x in rows(detail_groups(inst(city_type="rural"), "ru")).values()
    ] == ["Сельская местность"]


def test_detail_groups_seeded_keys() -> None:
    """ADM-INTL-11: keys of the seed data render without errors."""
    got = rows(
        detail_groups(
            inst(
                city_type="suburban",
                institution_type="private",
                test_policy="flexible",
                aid_basis="need_blind_full",
                merit_for_internationals=True,
                acceptance_rate={"min": 3.7, "max": 3.7},
                intl_tuition_usd=FactView(17700, "u", 2025, None, True, "EUR"),
            ),
            "uz",
        )
    )
    assert got["acceptance_rate"]["value_text"] == "3.7%"
    assert got["intl_tuition_usd"]["value_text"] == "EUR 17 700"
    assert got["aid_basis"]["value_text"].startswith("Ehtiyojni")
    assert got["merit_for_internationals"]["value_text"] == "Ha"


def test_importance_factors_order() -> None:
    """ADM-INTL-12: factors follow the registry order, unknown parts dropped."""
    got = importance_factors(
        inst(
            admission_factors={
                "essay": "very_important",
                "gpa": "considered",
                "zzz": "important",
            }
        ),
        "en",
    )
    assert got == [
        {"key": "gpa", "label": "GPA", "importance": "considered"},
        {"key": "essay", "label": "Essay", "importance": "very_important"},
    ]
    assert importance_factors(inst(), "en") == []
