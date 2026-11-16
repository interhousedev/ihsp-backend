"""College readiness routes (`/v1/admission/readiness`)."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, AnyContext, ContainerDep
from app.modules.admission.application.readiness import Readiness

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class ReadinessComponentOut(BaseModel):
    """One part of the score; `next_action` and `url_path` are null when complete."""

    key: str
    score: int = Field(ge=0, le=100)
    weight: float
    next_action: str | None
    url_path: str | None


class ReadinessOut(BaseModel):
    """Overall college readiness with its weighted parts."""

    percent: int = Field(ge=0, le=100)
    components: list[ReadinessComponentOut]

    @classmethod
    def of(cls, r: Readiness) -> "ReadinessOut":
        """Map the application result."""
        return cls(
            percent=r.percent,
            components=[
                ReadinessComponentOut(
                    key=c.key,
                    score=c.score,
                    weight=c.weight,
                    next_action=c.next_action,
                    url_path=c.url_path,
                )
                for c in r.components
            ],
        )


class ReadinessWeightsBody(BaseModel):
    """Weight per component key; the response uses the same shape."""

    weights: dict[str, float]


async def get_weights(container: ContainerDep, ctx: AnyContext) -> ReadinessWeightsBody:
    """The weights in force (administrators and counselors)."""
    return ReadinessWeightsBody(
        weights=await container.admission.readiness.weights(ctx)
    )


async def put_weights(
    body: ReadinessWeightsBody, container: ContainerDep, ctx: AnyContext
) -> ReadinessWeightsBody:
    """Replace the weights (administrators and counselors)."""
    saved = await container.admission.readiness.set_weights(ctx, body.weights)
    return ReadinessWeightsBody(weights=saved)


async def my_readiness(container: ContainerDep, ctx: AdmissionCtx) -> ReadinessOut:
    """My college readiness."""
    return ReadinessOut.of(await container.admission.readiness.get(ctx))


async def student_readiness(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ReadinessOut:
    """A student's readiness (staff in scope, same rule as the profile)."""
    return ReadinessOut.of(await container.admission.readiness.get(ctx, student_id))


router.add_api_route(
    "/readiness",
    my_readiness,
    methods=["GET"],
    response_model=ReadinessOut,
    operation_id="admission_readiness",
)
router.add_api_route(
    "/students/{student_id}/readiness",
    student_readiness,
    methods=["GET"],
    response_model=ReadinessOut,
    operation_id="admission_readiness_of_student",
)
router.add_api_route(
    "/readiness/weights",
    get_weights,
    methods=["GET"],
    response_model=ReadinessWeightsBody,
    operation_id="admission_readiness_weights",
)
router.add_api_route(
    "/readiness/weights",
    put_weights,
    methods=["PUT"],
    response_model=ReadinessWeightsBody,
    operation_id="admission_readiness_set_weights",
)
