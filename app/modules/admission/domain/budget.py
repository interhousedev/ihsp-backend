"""Application budget: what applying costs per university (ADM-BUDGET-*).

Pure arithmetic over plain inputs. Currencies are never mixed: every total is
kept per currency. A CSS Profile fee is only counted, never priced.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any
from uuid import UUID

FEE_STATUSES = ("unpaid", "paid", "waiver_requested", "waiver_approved")
AID_FORMS = ("css_profile", "fafsa", "idoc", "institutional")


@dataclass(frozen=True, slots=True)
class FeeFact:
    """The application fee of an institution, cited."""

    amount: Decimal
    currency: str
    source_url: str | None = None
    year: int | None = None


@dataclass(frozen=True, slots=True)
class AttendCost:
    """The yearly cost to attend with the aid estimate."""

    annual_cost: Decimal
    currency: str
    aid_estimate: Decimal | None = None
    gap: Decimal | None = None


@dataclass(frozen=True, slots=True)
class BudgetInput:
    """Everything the budget needs about one non-withdrawn list entry."""

    entry_id: UUID
    institution_id: UUID
    round: str
    fee_status: str
    fee: FeeFact | None
    aid_forms: tuple[str, ...]
    aid_forms_known: bool
    aid_deadline: str | None
    cost_to_attend: AttendCost | None


@dataclass(frozen=True, slots=True)
class BudgetRow:
    """One budget row; `item` is the input it was computed from."""

    item: BudgetInput


@dataclass(frozen=True, slots=True)
class CurrencyTotal:
    """Fee totals of one currency."""

    currency: str
    known_total: Decimal
    paid_total: Decimal
    waived_total: Decimal


@dataclass(frozen=True, slots=True)
class BudgetTotals:
    """Fee totals per currency plus counts of what cannot be priced."""

    by_currency: tuple[CurrencyTotal, ...]
    unknown_fee_count: int
    css_profile_schools: int


def money_fact(value: Any) -> tuple[Decimal, str] | None:
    """Amount and currency of a stored money value, or None."""
    if not isinstance(value, dict):
        return None
    amount, cur = value.get("amount"), value.get("currency")
    if isinstance(amount, bool) or not isinstance(amount, int | float | Decimal):
        return None
    if not isinstance(cur, str) or not cur:
        return None
    return Decimal(str(amount)), cur


def budget_totals(items: list[BudgetInput]) -> BudgetTotals:
    """Sum the fees per currency; only an approved waiver subtracts."""
    known: dict[str, Decimal] = {}
    paid: dict[str, Decimal] = {}
    waived: dict[str, Decimal] = {}
    unknown = 0
    css = 0
    for it in items:
        if "css_profile" in it.aid_forms:
            css += 1
        if it.fee is None:
            unknown += 1
            continue
        cur, amount = it.fee.currency, it.fee.amount
        known[cur] = known.get(cur, Decimal(0)) + amount
        if it.fee_status == "paid":
            paid[cur] = paid.get(cur, Decimal(0)) + amount
        elif it.fee_status == "waiver_approved":
            waived[cur] = waived.get(cur, Decimal(0)) + amount
    zero = Decimal(0)
    return BudgetTotals(
        by_currency=tuple(
            CurrencyTotal(c, known[c], paid.get(c, zero), waived.get(c, zero))
            for c in sorted(known)
        ),
        unknown_fee_count=unknown,
        css_profile_schools=css,
    )
