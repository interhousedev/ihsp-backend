"""Self-reported outcomes routes (`/v1/admission/outcomes*`)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AnyContext, ContainerDep
from app.modules.admission.application.outcomes import OutcomeSummary
from app.modules.admission.domain.institution_brand import InstitutionBrand
from app.modules.admission.domain.outcomes import (
    MAX_CYCLE,
    MIN_CYCLE,
    Outcome,
    OutcomeTally,
    SharedName,
)

from fastapi import APIRouter, Query, Response, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

StatusT = Literal[
    "applied", "accepted", "rejected", "waitlisted", "deferred", "enrolled"
]
PlanT = Literal["ed", "ed2", "ea", "rea", "rd", "rolling", "other"]
CycleT = Field(ge=MIN_CYCLE, le=MAX_CYCLE)


class OutcomeIn(BaseModel):
    """Report the outcome of an application; one per institution and cycle."""

    model_config = ConfigDict(extra="forbid")

    institution_id: UUID
    cycle: int = CycleT
    plan: PlanT = "rd"
    status: StatusT = "applied"
    share_name: bool = False


class OutcomePatch(BaseModel):
    """Change a report; `lock_version` guards against a concurrent edit."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int = Field(ge=0)
    plan: PlanT | None = None
    status: StatusT | None = None
    share_name: bool | None = None


class OutcomeOut(BaseModel):
    """A student's own report."""

    id: UUID
    institution_id: UUID
    cycle: int
    plan: str
    status: str
    share_name: bool
    lock_version: int
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, o: Outcome) -> "OutcomeOut":
        """Map the report."""
        return cls(
            id=o.id,
            institution_id=o.institution_id,
            cycle=o.cycle,
            plan=o.plan,
            status=o.status,
            share_name=o.share_name,
            lock_version=o.lock_version,
            updated_at=o.updated_at,
        )


class OutcomeListOut(BaseModel):
    """The caller's reports."""

    items: list[OutcomeOut]


class SharedNameOut(BaseModel):
    """A student listed with an outcome; `shared` is false only for staff views."""

    name: str
    status: str
    plan: str
    shared: bool

    @classmethod
    def of(cls, n: SharedName) -> "SharedNameOut":
        """Map the name."""
        return cls(name=n.name, status=n.status, plan=n.plan, shared=n.shared)


class OutcomeTallyOut(BaseModel):
    """Counts for one institution and cycle."""

    institution_id: UUID
    institution_name: str
    logo_url: str | None = None
    logo_fit: Literal["circle", "contain"] = "circle"
    logo_zoom: float = 1.0
    cycle: int
    applied: int
    accepted: int
    by_status: dict[str, int]
    names: list[SharedNameOut]

    @classmethod
    def of(
        cls, t: OutcomeTally, institutions: dict[UUID, InstitutionBrand]
    ) -> "OutcomeTallyOut":
        """Map the tally."""
        brand = institutions.get(t.institution_id) or InstitutionBrand("")
        return cls(
            institution_id=t.institution_id,
            institution_name=brand.name,
            logo_url=brand.logo_url,
            logo_fit=brand.logo_fit,
            logo_zoom=brand.logo_zoom,
            cycle=t.cycle,
            applied=t.reported,
            accepted=t.accepted,
            by_status=t.by_status,
            names=[SharedNameOut.of(n) for n in t.names],
        )


class OutcomeSummaryOut(BaseModel):
    """Where students applied; names only of those who agreed (staff see all)."""

    items: list[OutcomeTallyOut]
    applied: int
    accepted: int

    @classmethod
    def of(cls, s: OutcomeSummary) -> "OutcomeSummaryOut":
        """Map the summary."""
        return cls(
            items=[OutcomeTallyOut.of(t, s.institutions) for t in s.tallies],
            applied=s.reported,
            accepted=s.accepted,
        )


async def list_outcomes(container: ContainerDep, ctx: AnyContext) -> OutcomeListOut:
    """The caller's own reports."""
    rows = await container.admission.outcomes.mine(ctx)
    return OutcomeListOut(items=[OutcomeOut.of(o) for o in rows])


async def create_outcome(
    body: OutcomeIn, container: ContainerDep, ctx: AnyContext
) -> OutcomeOut:
    """Report an outcome (409 when the cycle is already reported)."""
    row = await container.admission.outcomes.create(
        ctx,
        institution_id=body.institution_id,
        cycle=body.cycle,
        plan=body.plan,
        status=body.status,
        share_name=body.share_name,
    )
    return OutcomeOut.of(row)


async def update_outcome(
    outcome_id: UUID, body: OutcomePatch, container: ContainerDep, ctx: AnyContext
) -> OutcomeOut:
    """Change the caller's report (409 on a stale `lock_version`)."""
    row = await container.admission.outcomes.update(
        ctx,
        outcome_id,
        lock_version=body.lock_version,
        plan=body.plan,
        status=body.status,
        share_name=body.share_name,
    )
    return OutcomeOut.of(row)


async def delete_outcome(
    outcome_id: UUID, container: ContainerDep, ctx: AnyContext
) -> Response:
    """Remove the caller's report."""
    await container.admission.outcomes.delete(ctx, outcome_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def outcome_summary(
    container: ContainerDep,
    ctx: AnyContext,
    institution_id: UUID | None = None,
    cycle: int | None = Query(default=None, ge=MIN_CYCLE, le=MAX_CYCLE),
) -> OutcomeSummaryOut:
    """Counts per institution and cycle; names only of students who agreed."""
    summary = await container.admission.outcomes.summary(
        ctx, institution_id=institution_id, cycle=cycle
    )
    return OutcomeSummaryOut.of(summary)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route(
    "/outcomes", list_outcomes, "GET", "outcomes_list", response_model=OutcomeListOut
)
_route(
    "/outcomes",
    create_outcome,
    "POST",
    "outcomes_create",
    response_model=OutcomeOut,
    status_code=status.HTTP_201_CREATED,
)
_route(
    "/outcomes/summary",
    outcome_summary,
    "GET",
    "outcomes_summary",
    response_model=OutcomeSummaryOut,
)
_route(
    "/outcomes/{outcome_id}",
    update_outcome,
    "PATCH",
    "outcomes_update",
    response_model=OutcomeOut,
)
_route(
    "/outcomes/{outcome_id}",
    delete_outcome,
    "DELETE",
    "outcomes_delete",
    status_code=status.HTTP_204_NO_CONTENT,
)
