"""Prompt map and idea fit routes (`/v1/admission/essays/prompt-map`, `ideas/fit`)."""

from typing import Any, Literal

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.modules.admission.application.essay_prompt_map import (
    IdeaFit,
    PromptFit,
    PromptMapView,
)
from app.modules.admission.domain.essay_flow import PromptRef
from app.modules.admission.domain.essays import IDEA_MAX

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class PromptRefOut(BaseModel):
    """One prompt: a Common App prompt (`institution_id` null) or a supplement."""

    key: str
    institution_id: str | None
    institution_name: str
    position: int
    prompt: str
    word_limit: int | None
    limit_unit: str
    required: bool
    in_list: bool

    @classmethod
    def of(cls, r: PromptRef) -> "PromptRefOut":
        """Build from a prompt reference."""
        return cls(
            key=r.key,
            institution_id=None if r.institution_id is None else str(r.institution_id),
            institution_name=r.institution_name,
            position=r.position,
            prompt=r.prompt,
            word_limit=r.word_limit,
            limit_unit=r.limit_unit,
            required=r.required,
            in_list=r.in_list,
        )


class PromptGroupOut(BaseModel):
    """Prompts one essay can answer."""

    key: str
    kind: Literal["common", "shared", "unique"]
    spread: float
    prompts: list[PromptRefOut]
    covered: bool = Field(description="An essay or slot already answers a member.")


class PromptMapOut(BaseModel):
    """The prompt map; `available` is false when no embedding model was reachable."""

    available: bool
    model: str
    delta: float
    groups: list[PromptGroupOut]

    @classmethod
    def of(cls, v: PromptMapView) -> "PromptMapOut":
        """Build from the service result."""
        return cls(
            available=v.available,
            model=v.map.model,
            delta=v.map.delta,
            groups=[
                PromptGroupOut(
                    key=g.key,
                    kind=g.kind,
                    spread=g.spread,
                    prompts=[PromptRefOut.of(p) for p in g.prompts],
                    covered=any(p.key in v.covered for p in g.prompts),
                )
                for g in v.map.groups
            ],
        )


class IdeaFitIn(BaseModel):
    """An idea text to match against the prompts."""

    text: str = Field(min_length=1, max_length=IDEA_MAX)


class PromptFitOut(BaseModel):
    """Fit of the idea to one prompt: 0 to 100."""

    prompt: PromptRefOut
    distance: float
    score: int

    @classmethod
    def of(cls, f: PromptFit) -> "PromptFitOut":
        """Build from a scored prompt."""
        return cls(prompt=PromptRefOut.of(f.prompt), distance=f.distance, score=f.score)


class IdeaFitOut(BaseModel):
    """Uncovered prompts, best fit first; empty when `available` is false."""

    available: bool
    model: str
    items: list[PromptFitOut]

    @classmethod
    def of(cls, r: IdeaFit) -> "IdeaFitOut":
        """Build from the service result."""
        return cls(
            available=r.available,
            model=r.model,
            items=[PromptFitOut.of(f) for f in r.items],
        )


async def get_prompt_map(container: ContainerDep, ctx: AdmissionCtx) -> PromptMapOut:
    """The prompts grouped into common, shared and unique clusters."""
    return PromptMapOut.of(await container.admission.essay_prompt_map.prompt_map(ctx))


async def fit_idea(
    body: IdeaFitIn, container: ContainerDep, ctx: AdmissionCtx
) -> IdeaFitOut:
    """Score an idea against the prompts no essay or slot covers (AI consent)."""
    return IdeaFitOut.of(await container.admission.essay_prompt_map.fit(ctx, body.text))


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_FORBIDDEN = {
    403: {"model": ProblemOut, "description": "Not the owner, or no AI consent."}
}
_INVALID = {422: {"model": ProblemOut, "description": "The idea text is empty."}}

_route(
    "/essays/prompt-map",
    get_prompt_map,
    "GET",
    "essay_prompt_map",
    response_model=PromptMapOut,
    responses={403: _FORBIDDEN[403]},
)
_route(
    "/essays/ideas/fit",
    fit_idea,
    "POST",
    "essay_idea_fit",
    response_model=IdeaFitOut,
    responses={**_FORBIDDEN, **_INVALID},
)
