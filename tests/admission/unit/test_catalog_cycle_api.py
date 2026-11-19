"""Catalog proposal cycles: only the current or next admission cycle is accepted."""

from datetime import date

from app.modules.admission.application.supp_prompts import clean_proposed
from app.modules.admission.domain.errors import CatalogCycleError
from app.modules.admission.domain.supp_prompts import proposal_cycles

import pytest


def _item(cycle: str) -> dict[str, object]:
    return {
        "cycle": cycle,
        "prompt": "Why us?",
        "word_limit": 250,
        "required": True,
        "source_url": "https://example.edu/apply",
    }


def test_cycles_follow_the_july_academic_year() -> None:
    """ADM-CAT-API-CYCLE: 2026-11-19 is in cycle 2026-27, next is 2027-28."""
    assert proposal_cycles(date(2026, 11, 19)) == {"2026-27", "2027-28"}
    assert proposal_cycles(date(2026, 3, 1)) == {"2025-26", "2026-27"}
    assert proposal_cycles(date(2026, 7, 1)) == {"2026-27", "2027-28"}


def test_year_turn_is_handled() -> None:
    """ADM-CAT-API-CYCLE: August 2099 opens cycle 2099-00, next is 2100-01."""
    assert "2099-00" in proposal_cycles(date(2099, 8, 1))


@pytest.mark.parametrize("cycle", ["2026-27", "2027-28"])
def test_current_and_next_cycle_are_accepted(cycle: str) -> None:
    """ADM-CAT-API-CYCLE: the open cycle and the next one pass."""
    out = clean_proposed([_item(cycle)], date(2026, 11, 19))
    assert out[0]["cycle"] == cycle


@pytest.mark.parametrize("cycle", ["2024-25", "2028-29", "2026-28", "2026-2027"])
def test_other_cycles_are_rejected(cycle: str) -> None:
    """ADM-CAT-API-CYCLE: past, far future, non-consecutive and malformed cycles
    raise CatalogCycleError with the cycle as a parameter."""
    with pytest.raises(CatalogCycleError) as err:
        clean_proposed([_item(cycle)], date(2026, 11, 19))
    assert err.value.params == {"cycle": cycle}
    assert err.value.code == "admission/catalog_cycle"
