"""Application budget arithmetic (ADM-BUDGET-*)."""

from decimal import Decimal
from uuid import uuid4

from app.modules.admission.domain.budget import (
    BudgetInput,
    FeeFact,
    budget_totals,
    money_fact,
)


def _i(
    fee: FeeFact | None,
    status: str = "unpaid",
    forms: tuple[str, ...] = (),
) -> BudgetInput:
    return BudgetInput(
        uuid4(), uuid4(), "RD", status, fee, forms, bool(forms), None, None
    )


def _usd(n: int) -> FeeFact:
    return FeeFact(Decimal(n), "USD")


def test_totals_paid_and_waived() -> None:
    """ADM-BUDGET-1: only a paid or approved-waiver fee moves its own total."""
    t = budget_totals(
        [
            _i(_usd(75), "paid"),
            _i(_usd(90), "waiver_approved"),
            _i(_usd(60), "waiver_requested"),
            _i(_usd(50)),
        ]
    )
    (usd,) = t.by_currency
    assert (usd.known_total, usd.paid_total, usd.waived_total) == (275, 75, 90)


def test_currencies_never_mixed() -> None:
    """ADM-BUDGET-2: fees of different currencies get separate totals."""
    t = budget_totals([_i(_usd(75)), _i(FeeFact(Decimal(30), "GBP"))])
    assert [(c.currency, c.known_total) for c in t.by_currency] == [
        ("GBP", 30),
        ("USD", 75),
    ]


def test_unknown_fee_counted_not_priced() -> None:
    """ADM-BUDGET-3: a missing fee is counted and adds nothing."""
    t = budget_totals([_i(None), _i(None, "paid"), _i(_usd(10))])
    assert t.unknown_fee_count == 2
    assert t.by_currency[0].known_total == 10


def test_css_profile_counted_without_amount() -> None:
    """ADM-BUDGET-4: CSS Profile schools are counted, never priced."""
    t = budget_totals(
        [_i(_usd(10), forms=("css_profile", "fafsa")), _i(None, forms=("fafsa",))]
    )
    assert t.css_profile_schools == 1
    assert t.by_currency[0].known_total == 10


def test_money_fact_parsing() -> None:
    """ADM-BUDGET-5: a money fact needs a numeric amount and a currency."""
    assert money_fact({"amount": 75, "currency": "USD"}) == (Decimal(75), "USD")
    assert money_fact({"amount": "x", "currency": "USD"}) is None
    assert money_fact(None) is None
