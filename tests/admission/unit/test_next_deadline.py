"""Institution `next_deadline` and the `deadline` sort (cycle-aware, nulls last)."""

import datetime as dt

from app.modules.admission.domain.chooser import (
    CatalogInstitution,
    FactView,
    next_deadline,
    sort_by_deadline,
)
from app.shared.ids import new_id

TODAY = dt.date(2026, 3, 10)


def _inst(name: str, dates: list[str] | None) -> CatalogInstitution:
    facts: dict[str, FactView] = {}
    if dates is not None:
        raw = [{"plan": "RD", "date": d} for d in dates]
        facts["deadlines"] = FactView(raw, "u", 2026, None, True)
    return CatalogInstitution(new_id(), "x", name, "UZ", "T", "published", facts)


def test_no_deadlines_gives_none() -> None:
    assert next_deadline(_inst("A", None), TODAY) is None
    assert next_deadline(_inst("B", []), TODAY) is None


def test_past_only_gives_none() -> None:
    assert next_deadline(_inst("A", ["2026-03-09"]), TODAY) is None


def test_earliest_future_date_wins() -> None:
    inst = _inst("A", ["2026-12-01", "2026-03-10", "2026-04-02", "2026-03-01"])
    assert next_deadline(inst, TODAY) == dt.date(2026, 3, 10)


def test_today_itself_counts() -> None:
    assert next_deadline(_inst("A", ["2026-03-10"]), TODAY) == TODAY


def test_deadline_sort_soonest_first_nulls_last() -> None:
    late = _inst("Late", ["2026-11-01"])
    soon = _inst("Soon", ["2026-03-20"])
    none = _inst("None", None)
    past = _inst("Past", ["2026-01-01"])
    ordered = sort_by_deadline([none, late, past, soon], TODAY)
    assert [i.name for i in ordered] == ["Soon", "Late", "None", "Past"]


def test_deadline_sort_ties_by_name() -> None:
    b = _inst("Beta", ["2026-05-01"])
    a = _inst("alpha", ["2026-05-01"])
    assert [i.name for i in sort_by_deadline([b, a], TODAY)] == ["alpha", "Beta"]


def test_tashkent_day_boundary_uses_given_today() -> None:
    # A deadline of 2026-03-10 is still upcoming on that Tashkent day and
    # drops out the next day; the caller supplies the Tashkent date.
    inst = _inst("A", ["2026-03-10"])
    assert next_deadline(inst, dt.date(2026, 3, 10)) == dt.date(2026, 3, 10)
    assert next_deadline(inst, dt.date(2026, 3, 11)) is None
