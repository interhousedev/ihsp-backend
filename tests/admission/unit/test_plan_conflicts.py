"""Early-application plan conflicts (ADM-U3-*)."""

from uuid import UUID, uuid4

from app.modules.admission.domain.plan_conflicts import PlanEntry, plan_conflicts


def _e(
    round_: str, country: str | None = "US", kind: str | None = "private"
) -> PlanEntry:
    return PlanEntry(uuid4(), round_, country, kind)


def _codes(entries: list[PlanEntry]) -> list[tuple[str, str]]:
    return [(c.code, c.severity) for c in plan_conflicts(entries)]


def test_multiple_ed() -> None:
    """ADM-U3-1: two ED plans conflict and name both entries."""
    a, b = _e("ED"), _e("ED")
    (c,) = plan_conflicts([a, b])
    assert (c.code, c.severity) == ("multiple_ed", "conflict")
    assert set(c.entry_ids) == {a.id, b.id}


def test_ed_with_restrictive() -> None:
    """ADM-U3-2: ED with REA or SCEA conflicts."""
    assert ("ed_with_restrictive", "conflict") in _codes([_e("ED"), _e("SCEA")])
    assert ("ed_with_restrictive", "conflict") in _codes([_e("ED"), _e("REA")])


def test_multiple_restrictive_and_ed2() -> None:
    """ADM-U3-3: two REA/SCEA or two ED2 plans conflict."""
    assert _codes([_e("REA"), _e("SCEA")]) == [("multiple_restrictive", "conflict")]
    assert _codes([_e("ED2"), _e("ED2")]) == [("multiple_ed2", "conflict")]


def test_restrictive_with_early_known_private_us() -> None:
    """ADM-U3-4: REA with EA at another private US school conflicts."""
    assert _codes([_e("REA"), _e("EA")]) == [("restrictive_with_early", "conflict")]


def test_restrictive_with_early_unknown_is_check() -> None:
    """ADM-U3-5: unknown control or country is a check, never silence."""
    assert _codes([_e("REA"), _e("EA", None, "private")]) == [
        ("restrictive_with_early", "check")
    ]
    assert _codes([_e("REA"), _e("EA", "US", None)]) == [
        ("restrictive_with_early", "check")
    ]


def test_restrictive_with_early_public_or_foreign_is_clear() -> None:
    """ADM-U3-6: a public or non-US early plan raises nothing."""
    assert _codes([_e("REA"), _e("EA", "US", "public")]) == []
    assert _codes([_e("SCEA"), _e("EA", "GB", "private")]) == []


def test_no_conflicts() -> None:
    """ADM-U3-7: one early plan plus RD is fine."""
    assert plan_conflicts([_e("ED"), _e("RD"), _e("EA")]) == ()
    assert isinstance(_e("RD").id, UUID)
