"""Fit of each university list entry (`/v1/admission/list/fit`)."""

from typing import Annotated

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_fit import AxisWeightsOut
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.fit import ListFit

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])
Lang = Annotated[str | None, Header(alias="Accept-Language")]


class RaiseOut(BaseModel):
    """A step that moves an axis."""

    label: str
    href: str
    gain: int


class AxisFitOut(BaseModel):
    """One fit axis; `score` is null when its data is missing."""

    key: str
    score: int | None
    weight: float
    why: list[str]
    raise_: list[RaiseOut] = Field(serialization_alias="raise")


class FitItemOut(BaseModel):
    """The fit of one list entry."""

    list_entry_id: str
    institution_id: str
    total: int | None
    axes: list[AxisFitOut]


class ListFitOut(BaseModel):
    """Weights and the fit of every list entry."""

    weights: AxisWeightsOut
    items: list[FitItemOut]

    @classmethod
    def of(cls, v: ListFit) -> "ListFitOut":
        """Map the application result."""
        return cls(
            weights=AxisWeightsOut(**v.weights),
            items=[
                FitItemOut(
                    list_entry_id=str(i.list_entry_id),
                    institution_id=str(i.institution_id),
                    total=i.fit.total,
                    axes=[
                        AxisFitOut(
                            key=a.key,
                            score=a.score,
                            weight=a.weight,
                            why=list(a.why),
                            raise_=[
                                RaiseOut(label=r.label, href=r.href, gain=r.gain)
                                for r in a.raises
                            ],
                        )
                        for a in i.fit.axes
                    ],
                )
                for i in v.items
            ],
        )


async def get_list_fit(
    container: ContainerDep, ctx: StudentCtx, accept_language: Lang = None
) -> ListFitOut:
    """Fit of each entry of my list, from my preferences and plan."""
    res = await container.admission.fit.list_fit(ctx, _locale(accept_language))
    return ListFitOut.of(res)


router.add_api_route(
    "/list/fit",
    get_list_fit,
    methods=["GET"],
    response_model=ListFitOut,
    response_model_by_alias=True,
    operation_id="admission_get_list_fit",
)
