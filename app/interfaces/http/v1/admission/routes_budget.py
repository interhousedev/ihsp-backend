"""Application budget route: what applying costs per university."""

from decimal import Decimal
from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_chooser import (
    CYCLE_RE,
    FeeStatus,
    Lang,
)
from app.modules.admission.application.budget import BudgetView
from app.modules.admission.domain.budget import AttendCost, FeeFact
from app.modules.admission.domain.catalog_display import resolve_logo_fit
from app.modules.admission.domain.chooser import CatalogInstitution

from fastapi import APIRouter, Query
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admission", tags=["admission"])

AidForm = Literal["css_profile", "fafsa", "idoc", "institutional"]


class BudgetInstitutionOut(BaseModel):
    """The institution fields the budget table shows."""

    id: UUID
    name: str
    logo_url: str | None
    logo_fit: Literal["circle", "contain"]
    logo_zoom: float

    @classmethod
    def of(cls, i: CatalogInstitution) -> "BudgetInstitutionOut":
        """Map the institution."""
        return cls(
            id=i.id,
            name=i.name,
            logo_url=i.logo_url,
            logo_fit=resolve_logo_fit(i.logo_fit, i.logo_aspect),
            logo_zoom=i.logo_zoom,
        )


class ApplicationFeeOut(BaseModel):
    """A cited application fee."""

    amount: Decimal
    currency: str
    source_url: str | None
    year: int | None

    @classmethod
    def of(cls, f: FeeFact) -> "ApplicationFeeOut":
        """Map the fee."""
        return cls(
            amount=f.amount, currency=f.currency, source_url=f.source_url, year=f.year
        )


class CostToAttendOut(BaseModel):
    """Yearly cost to attend; separate from the cost to apply."""

    annual_cost: Decimal
    currency: str
    aid_estimate: Decimal | None
    gap: Decimal | None

    @classmethod
    def of(cls, c: AttendCost) -> "CostToAttendOut":
        """Map the cost."""
        return cls(
            annual_cost=c.annual_cost,
            currency=c.currency,
            aid_estimate=c.aid_estimate,
            gap=c.gap,
        )


class BudgetRowOut(BaseModel):
    """One list entry of the budget."""

    entry_id: UUID
    institution: BudgetInstitutionOut
    round: str
    application_fee: ApplicationFeeOut | None
    fee_status: FeeStatus
    aid_forms: list[AidForm]
    aid_forms_known: bool
    aid_deadline: str | None
    cost_to_attend: CostToAttendOut | None


class CurrencyTotalOut(BaseModel):
    """Fee totals of one currency."""

    currency: str
    known_total: Decimal
    paid_total: Decimal
    waived_total: Decimal


class BudgetTotalsOut(BaseModel):
    """Totals per currency; currencies are never summed together."""

    by_currency: list[CurrencyTotalOut]
    unknown_fee_count: int
    css_profile_schools: int


class BudgetOut(BaseModel):
    """The application budget of a list."""

    rows: list[BudgetRowOut]
    totals: BudgetTotalsOut

    @classmethod
    def of(cls, v: BudgetView) -> "BudgetOut":
        """Map the view."""
        return cls(
            rows=[
                BudgetRowOut(
                    entry_id=r.entry_id,
                    institution=BudgetInstitutionOut.of(inst),
                    round=r.round,
                    application_fee=(
                        ApplicationFeeOut.of(r.fee) if r.fee is not None else None
                    ),
                    fee_status=r.fee_status,
                    aid_forms=list(r.aid_forms),
                    aid_forms_known=r.aid_forms_known,
                    aid_deadline=r.aid_deadline,
                    cost_to_attend=(
                        CostToAttendOut.of(r.cost_to_attend)
                        if r.cost_to_attend is not None
                        else None
                    ),
                )
                for r, inst in v.rows
            ],
            totals=BudgetTotalsOut(
                by_currency=[
                    CurrencyTotalOut(
                        currency=t.currency,
                        known_total=t.known_total,
                        paid_total=t.paid_total,
                        waived_total=t.waived_total,
                    )
                    for t in v.totals.by_currency
                ],
                unknown_fee_count=v.totals.unknown_fee_count,
                css_profile_schools=v.totals.css_profile_schools,
            ),
        )


async def get_budget(
    container: ContainerDep,
    ctx: AdmissionCtx,
    student_id: UUID | None = None,
    cycle: str | None = Query(None, pattern=CYCLE_RE),
    accept_language: Lang = None,
) -> BudgetOut:
    """Return the application budget of my list (staff pass `student_id`).

    Unreadable students answer 404. Cost to attend is null where the caller
    may not see amounts.
    """
    view = await container.admission.budget.view(ctx, student_id or ctx.user_id, cycle)
    return BudgetOut.of(view)


router.add_api_route(
    "/chooser/budget",
    get_budget,
    methods=["GET"],
    response_model=BudgetOut,
    operation_id="admission_chooser_budget",
    status_code=200,
)
