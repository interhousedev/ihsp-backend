"""Fit axes: scoring from fixtures, null for unknown data, localised lines."""

from decimal import Decimal
from uuid import uuid4

from app.modules.admission.domain.chooser import CatalogInstitution, FactView
from app.modules.admission.domain.fit import (
    DEFAULT_WEIGHTS,
    AxisFit,
    EntryFit,
    FitResult,
    StudentFit,
    compute_fit,
    default_ratings,
)
from app.modules.admission.domain.professions import Profession

import pytest


def _inst(**kw: object) -> CatalogInstitution:
    base: dict[str, object] = {
        "id": uuid4(),
        "slug": "u",
        "name": "U",
        "country": "UZ",
        "city": None,
        "status": "published",
    }
    return CatalogInstitution(**(base | kw))  # type: ignore[arg-type]


def _prof(
    fields: tuple[str, ...], risk: str = "low", band: str | None = "high"
) -> Profession:
    return Profession(
        "2512",
        "2",
        {"en": "Developer", "ru": "Разработчик"},
        0.3,
        risk,  # type: ignore[arg-type]
        "5y",
        fields,
        band,  # type: ignore[arg-type]
    )


def _axes(
    student: StudentFit, entry: EntryFit, loc: str = "en"
) -> tuple[FitResult, dict[str, AxisFit]]:
    res = compute_fit(student, entry, DEFAULT_WEIGHTS, loc)
    return res, {a.key: a for a in res.axes}


def test_nothing_known_gives_null_axes_and_no_total() -> None:
    res, ax = _axes(StudentFit(), EntryFit(_inst(country="")))
    assert res.total is None or ax["traits"].score is not None
    assert ax["afford"].score is None and ax["goals"].score is None
    assert ax["afford"].raises[0].href == "/chooser/?step=quiz"


def test_afford_within_and_over_budget() -> None:
    cheap = _inst(coa_total=Decimal(4000), coa_currency="USD")
    dear = _inst(coa_total=Decimal(30000), coa_currency="USD")
    s = StudentFit(budget_band="under_5k")
    assert _axes(s, EntryFit(cheap))[1]["afford"].score == 100
    over = _axes(s, EntryFit(dear))[1]["afford"]
    assert over.score == 0 and over.raises


def test_goals_use_profession_fields_and_unknown_without_picks() -> None:
    inst = _inst(facts={"fields": FactView(["computer_science"])})
    s = StudentFit(professions=(_prof(("computer_science",)),))
    ax = _axes(s, EntryFit(inst))[1]["goals"]
    assert ax.score is not None and ax.score >= 80
    assert "Developer" in ax.why[0]
    assert _axes(StudentFit(), EntryFit(inst))[1]["goals"].score is None
    miss = _axes(StudentFit(professions=(_prof(("law",)),)), EntryFit(inst))
    assert miss[1]["goals"].score == 0


def test_profile_estimate_and_missing_tests() -> None:
    inst = _inst(facts={"test_policy": FactView("required")})
    s = StudentFit(focus_fields=("computer_science",))
    ax = _axes(s, EntryFit(inst, "target"))[1]["profile"]
    assert ax.score is not None and any(r.href == "/tests" for r in ax.raises)
    done = _axes(
        StudentFit(focus_fields=("computer_science",), has_scores=True),
        EntryFit(inst, "target"),
    )[1]["profile"]
    assert done.score == 70


def test_traits_from_facts_and_distance() -> None:
    inst = _inst(facts={"city_type": FactView("urban")}, country="UZ")
    ax = _axes(StudentFit(), EntryFit(inst))[1]["traits"]
    assert ax.score == 100
    far = _axes(StudentFit(), EntryFit(_inst(country="US")))[1]["traits"]
    assert far.score is not None and far.score < 100


def test_total_skips_unknown_axes_and_copy_is_localised() -> None:
    inst = _inst(coa_total=Decimal(1000), coa_currency="USD")
    s = StudentFit(budget_band="under_5k")
    res, ax = _axes(s, EntryFit(inst), "ru")
    assert res.total is not None
    assert ax["afford"].why[0] != _axes(s, EntryFit(inst), "en")[1]["afford"].why[0]
    assert ax["goals"].score is None


def test_default_ratings_are_five() -> None:
    assert set(default_ratings().values()) == {5}
    assert pytest.approx(sum(DEFAULT_WEIGHTS.values())) == 1
