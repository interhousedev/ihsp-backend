"""Chances: factors, status, curve, the service and https-only media."""

import dataclasses
from decimal import Decimal
from typing import Any

from app.modules.admission.application.chances import ChancesService
from app.modules.admission.application.runtime_settings import RuntimeSettingsService
from app.modules.admission.domain.chances import (
    Preferences,
    StudentData,
    admission_rate,
    evaluate,
)
from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.errors import (
    AdmissionNotFoundError,
    InvalidMediaUrlError,
)
from app.modules.admission.domain.matching import PreferenceAnswers
from app.modules.admission.domain.runtime_settings import ESTIMATES_STUDENT_VISIBLE
from app.settings_admission import AdmissionSettings
from app.shared.ids import new_id
from tests.admission.unit.fakes import FakeUow
from tests.admission.unit.test_catalog_proposals import (
    NEW,
)
from tests.admission.unit.test_catalog_proposals import World as ProposalWorld
from tests.admission.unit.test_catalog_proposals import _curator, _propose
from tests.admission.unit.test_chooser_service import World

import pytest


def _inst(
    rate: tuple[int, int] | None, coa: int | None = 20000, **facts: Any
) -> CatalogInstitution:
    f = {k: FactView(v, "https://s", 2025) for k, v in facts.items()}
    if rate:
        f["acceptance_rate"] = FactView({"min": rate[0], "max": rate[1]}, "x", 2025)
    return CatalogInstitution(
        new_id(), "u", "U", "US", None, "published", f,
        coa_total=Decimal(coa) if coa else None, coa_currency="USD",
    )  # fmt: skip


def _by_key(c: Any) -> dict[str, Any]:
    return {f.key: f for f in c.factors}


def test_rate_is_international_first() -> None:
    i = _inst((40, 60), intl_acceptance_rate={"min": 10, "max": 20})
    assert admission_rate(i) == pytest.approx(0.15)


def test_selective_school_is_reach_even_with_strong_gpa() -> None:
    c = evaluate(_inst((4, 6), median_gpa=90), StudentData(gpa_ratio=1.0))
    assert c.status == "reach"
    assert c.summary_key == "reach_selective"
    assert _by_key(c)["academics"].level == "strong"


def test_strong_academics_lift_target_to_safety() -> None:
    c = evaluate(_inst((40, 50), median_gpa=80), StudentData(gpa_ratio=0.95))
    assert c.status == "safety"


def test_weak_academics_drop_target_to_reach() -> None:
    c = evaluate(_inst((40, 50), median_gpa=95), StudentData(gpa_ratio=0.7))
    assert c.status == "reach"
    assert c.summary_key == "reach_academics"
    a = _by_key(c)["academics"]
    assert a.level == "weak" and a.action is not None


def test_unknown_without_rate_or_grades() -> None:
    c = evaluate(_inst(None), StudentData())
    assert c.status is None and c.summary_key == "unknown_data"
    assert all(f.level == "unknown" for f in c.factors[:2])
    assert c.simulation.points == ()


def test_score_metric_when_sat_and_median_exist() -> None:
    i = _inst((30, 40), sat_median=1400)
    c = evaluate(i, StudentData(gpa_ratio=0.9, sat_total=1450))
    assert c.simulation.metric == "score"
    assert c.simulation.your_value == 1450 and c.simulation.median == 1400
    assert _by_key(c)["academics"].level == "strong"
    xs = [p[0] for p in c.simulation.points]
    ch = [p[1] for p in c.simulation.points]
    assert xs == sorted(xs) and ch == sorted(ch)
    assert all(0 <= v <= 100 for v in ch)


def test_cost_uses_budget_preference_and_aid() -> None:
    i = _inst((30, 40), coa=60000)
    weak = _by_key(evaluate(i, StudentData(prefs=Preferences(budget="under_30k"))))
    assert weak["cost"].level == "weak" and weak["cost"].detail["gap"] == 30000
    ok = _by_key(evaluate(i, StudentData(prefs=Preferences(budget="under_50k"))))
    assert ok["cost"].level == "weak"  # no aid known
    i2 = CatalogInstitution(
        i.id, "u", "U", "US", None, "published", i.facts,
        coa_total=Decimal(60000), coa_currency="USD", merit_available=True,
    )  # fmt: skip
    assert (
        _by_key(evaluate(i2, StudentData(prefs=Preferences(budget="under_50k"))))[
            "cost"
        ].level
        == "ok"
    )
    assert _by_key(evaluate(i, StudentData()))["cost"].level == "unknown"
    assert (
        _by_key(evaluate(i, StudentData(prefs=Preferences(budget="any"))))["cost"].level
        == "strong"
    )


def test_location_activities_and_rigor() -> None:
    i = _inst((30, 40))
    f = _by_key(
        evaluate(
            i,
            StudentData(
                activities=7,
                course_titles=["AP Physics", "IB Math HL", "Art"],
                course_levels=[None, None, None],
                prefs=Preferences(region=("GB", "FR")),
            ),
        )
    )
    assert f["location"].level == "weak" and f["location"].detail["region"] == "GB,FR"
    assert f["activities"].level == "strong"
    assert f["course_rigor"].detail == {"advanced": 2, "total": 3}
    assert f["course_rigor"].level == "ok"


def _svc(w: World, uow: Any) -> ChancesService:
    return ChancesService(
        lambda: uow(w.store),
        RuntimeSettingsService(lambda: FakeUow(w.store), ttl=0),
        AdmissionSettings(),
    )


def test_non_usd_cost_is_unknown() -> None:
    i = _inst((30, 40), coa=60000)
    i = dataclasses.replace(i, coa_currency="KRW")
    f = _by_key(evaluate(i, StudentData(prefs=Preferences(budget="any"))))
    assert f["cost"].level == "unknown" and "cost" not in f["cost"].detail
    j = _inst((30, 40), coa=None, intl_coa_usd={"value": 9000, "currency": "KRW"})
    f = _by_key(evaluate(j, StudentData(prefs=Preferences(budget="any"))))
    assert f["cost"].level == "unknown"


def test_median_gpa_is_normalised_by_declared_scale() -> None:
    i = _inst((30, 40), median_gpa={"value": 3.6, "scale": 4.0})
    c = evaluate(i, StudentData(gpa_ratio=0.9))
    assert c.simulation.median == 90.0
    j = _inst((30, 40), median_gpa=3.6)  # undeclared small number: not a percent
    assert (
        _by_key(evaluate(j, StudentData(gpa_ratio=0.9)))["academics"].detail[
            "estimated"
        ]
        == 1
    )


def test_no_add_grades_action_when_gpa_is_present() -> None:
    i = _inst(None)
    f = _by_key(evaluate(i, StudentData(gpa_ratio=0.9)))
    assert f["academics"].level == "unknown" and f["academics"].action is None
    f = _by_key(evaluate(i, StudentData()))
    assert f["academics"].action.kind == "add_grades"


def test_threshold_is_none_outside_the_chart() -> None:
    c = evaluate(_inst((1, 2), median_gpa=95), StudentData(gpa_ratio=0.9))
    assert c.simulation.threshold is None


async def test_estimates_hidden_returns_factors_only() -> None:
    w = World()
    uid = w.inst()
    ctx = await w.student()

    class _Uow(FakeUow):
        def __init__(self, s: Any) -> None:
            super().__init__(s)
            self.items: Any = _Empty()
            self.test_scores: Any = _Empty()
            self.preferences: Any = _Prefs()

    w.store.runtime[ESTIMATES_STUDENT_VISIBLE] = False
    c = await _svc(w, _Uow).for_institution(ctx, uid)
    assert c.status is None and len(c.factors) == 5
    assert c.simulation.points == () and c.simulation.threshold is None


async def test_service_unknown_university_and_empty_student() -> None:
    w = World()
    uid = w.inst()
    ctx = await w.student()

    class _Uow(FakeUow):
        def __init__(self, s: Any) -> None:
            super().__init__(s)
            self.items: Any = _Empty()
            self.test_scores: Any = _Empty()
            self.preferences: Any = _Prefs()

    w.store.runtime[ESTIMATES_STUDENT_VISIBLE] = True
    svc = _svc(w, _Uow)
    with pytest.raises(AdmissionNotFoundError):
        await svc.for_institution(ctx, new_id())
    c = await svc.for_institution(ctx, uid)
    assert c.simulation.metric == "gpa"
    assert len(c.factors) == 5
    f = _by_key(c)
    assert f["location"].detail["region"] == "GB"
    assert f["location"].action.href == "/chooser/search/?prefs=1"


class _Prefs:
    async def get(self, student_id: Any) -> Any:
        return PreferenceAnswers(region=("GB",), budget="under_10k"), None


class _Empty:
    async def list_for(self, student_id: Any) -> list[Any]:
        return []

    async def entries(self, student_id: Any) -> list[Any]:
        return []

    async def catalog(self, *, include_inactive: bool) -> list[Any]:
        return []


async def test_media_urls_must_be_https() -> None:
    w = ProposalWorld()
    ctx = await _curator(w)
    with pytest.raises(InvalidMediaUrlError):
        await _propose(w, ctx, fields=NEW | {"logo_url": "http://x.edu/l.png"})
    with pytest.raises(InvalidMediaUrlError):
        await _propose(w, ctx, fields=NEW | {"cover_url": "javascript:alert(1)"})
    await _propose(w, ctx, fields=NEW | {"logo_url": "https://x.edu/l.png"})


def test_https_url_rejects_unsafe_characters() -> None:
    from app.modules.admission.domain.urls import is_https_url

    assert is_https_url("https://x.uz/a.png")
    for bad in ("https://x.uz/a b", 'https://x.uz/"', "https://x.uz/(a)", "https://x/'",
                "https://x.uz/\\a", "http://x.uz", "https://x.uz/a\nb"):  # fmt: skip
        assert not is_https_url(bad)


def test_rate_reads_scalar_intl_fact_in_both_rate_readers() -> None:
    from app.modules.admission.domain.estimates import _rate

    i = _inst((40, 60), intl_acceptance_rate=2.5)
    assert admission_rate(i) == pytest.approx(0.025)
    rate, basis = _rate(i)
    assert rate == 2.5 and basis["cohort"] == "international"
