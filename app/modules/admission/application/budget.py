"""The application budget of a student's list (ADM-BUDGET-*)."""

from dataclasses import dataclass
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.chooser import ListItem, ListService
from app.modules.admission.domain.budget import (
    AID_FORMS,
    AttendCost,
    BudgetInput,
    BudgetTotals,
    FeeFact,
    admit_rate_of,
    budget_totals,
    estimated_aid,
    money_fact,
)
from app.modules.admission.domain.chooser import CatalogInstitution


def _fee(inst: CatalogInstitution) -> FeeFact | None:
    f = inst.fact("application_fee")
    money = money_fact(f.value) if f is not None else None
    if f is None or money is None:
        return None
    return FeeFact(money[0], money[1], f.source_url, f.year)


def _attend(item: ListItem) -> AttendCost | None:
    """Cost to attend from the stored check; hidden when amounts are hidden."""
    inst, check = item.institution, item.affordability
    if not item.amounts_visible:
        return None
    if check is not None and check.coa_total is not None and inst.coa_currency:
        aid = (
            check.confirmed_aid
            if check.confirmed_aid is not None
            else check.estimated_aid
        )
        if aid is None:
            aid = estimated_aid(check.coa_total, inst.coa_currency, inst.aid_profile)
        return AttendCost(check.coa_total, inst.coa_currency, aid, check.gap)
    if inst.coa_total is not None and inst.coa_currency:
        aid = estimated_aid(inst.coa_total, inst.coa_currency, inst.aid_profile)
        return AttendCost(inst.coa_total, inst.coa_currency, aid)
    return None


def to_input(item: ListItem) -> BudgetInput:
    """Flatten one list item into budget inputs."""
    inst = item.institution
    forms = inst.fact("aid_forms")
    deadline = inst.fact("intl_aid_deadline")
    return BudgetInput(
        entry_id=item.entry.id,
        institution_id=inst.id,
        round=item.entry.round,
        fee_status=item.entry.fee_status,
        fee=_fee(inst),
        aid_forms=tuple(
            f for f in AID_FORMS if forms is not None and f in list(forms.value)
        ),
        aid_forms_known=forms is not None,
        aid_deadline=str(deadline.value) if deadline is not None else None,
        cost_to_attend=_attend(item),
        aid_profile=inst.aid_profile,
        admit_rate=admit_rate_of(
            inst.fact("intl_acceptance_rate"), inst.fact("acceptance_rate")
        ),
    )


@dataclass(frozen=True, slots=True)
class BudgetView:
    """The budget rows with their institutions and the totals."""

    rows: list[tuple[BudgetInput, CatalogInstitution]]
    totals: BudgetTotals


class BudgetService:
    """Reads the budget through the list service, so access rules stay shared."""

    def __init__(self, chooser: ListService) -> None:
        """Keep the list service."""
        self._chooser = chooser

    async def view(
        self, ctx: AdmissionContext, student_id: UUID, cycle: str | None = None
    ) -> BudgetView:
        """Budget of a student the caller may read; withdrawn entries are out."""
        items = [
            i
            for i in await self._chooser.view(ctx, student_id, cycle)
            if i.entry.status != "withdrawn"
        ]
        rows = [(to_input(i), i.institution) for i in items]
        return BudgetView(rows, budget_totals([r for r, _ in rows]))
