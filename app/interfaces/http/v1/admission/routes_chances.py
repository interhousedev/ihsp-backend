"""Student-scoped chances at one university."""

from typing import Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.domain.chances import Chances

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class ChanceActionOut(BaseModel):
    """Where the student can improve a factor."""

    kind: str
    href: str


class ChanceDetailOut(BaseModel):
    """Numbers and names the web renders into the factor text."""

    params: dict[str, str | int | float]


class ChanceFactorOut(BaseModel):
    """One judged dimension."""

    key: Literal["academics", "course_rigor", "cost", "location", "activities"]
    level: Literal["strong", "ok", "weak", "unknown"]
    detail: ChanceDetailOut
    action: ChanceActionOut | None


class ChancePointOut(BaseModel):
    """Chance (percent) at one value of the metric."""

    x: float
    chance: float = Field(ge=0, le=100)


class ChanceSimulationOut(BaseModel):
    """Chance curve around the university's median."""

    metric: Literal["gpa", "score"]
    your_value: float | None
    median: float | None
    threshold: float | None
    points: list[ChancePointOut]


class ChancesOut(BaseModel):
    """Status, its reason and the factors."""

    status: Literal["safety", "target", "reach"] | None
    summary_key: str
    factors: list[ChanceFactorOut]
    simulation: ChanceSimulationOut

    @classmethod
    def of(cls, c: Chances) -> "ChancesOut":
        """Map the domain result."""
        return cls(
            status=c.status,
            summary_key=c.summary_key,
            factors=[
                ChanceFactorOut(
                    key=f.key,
                    level=f.level,
                    detail=ChanceDetailOut(params=dict(f.detail)),
                    action=(
                        ChanceActionOut(kind=f.action.kind, href=f.action.href)
                        if f.action
                        else None
                    ),
                )
                for f in c.factors
            ],
            simulation=ChanceSimulationOut(
                metric=c.simulation.metric,
                your_value=c.simulation.your_value,
                median=c.simulation.median,
                threshold=c.simulation.threshold,
                points=[ChancePointOut(x=x, chance=p) for x, p in c.simulation.points],
            ),
        )


async def get_university_chances(
    university_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ChancesOut:
    """Judge the caller's chances at a university."""
    return ChancesOut.of(
        await container.admission.chances.for_institution(ctx, university_id)
    )


router.add_api_route(
    "/universities/{university_id}/chances",
    get_university_chances,
    methods=["GET"],
    response_model=ChancesOut,
    operation_id="admission_get_university_chances",
)
