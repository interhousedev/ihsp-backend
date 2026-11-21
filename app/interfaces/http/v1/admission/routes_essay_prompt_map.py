"""Prompt map and idea fit routes (`/v1/admission/essays/prompt-map`, `ideas/fit`)."""

import datetime as dt
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_essays import Lang
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.essay_prompt_map import (
    GroupView,
    IdeaFit,
    PromptFit,
    PromptMapView,
)
from app.modules.admission.domain.essay_categories import Category, ShortAnswer
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


class ShortAnswerOut(BaseModel):
    """A short answer to one prompt; `word_count` counts whitespace-separated words."""

    prompt_key: str
    text: str
    word_count: int
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, a: ShortAnswer) -> "ShortAnswerOut":
        """Build from a stored short answer."""
        return cls(
            prompt_key=a.prompt_key,
            text=a.text,
            word_count=a.word_count,
            updated_at=a.updated_at,
        )


class PromptGroupOut(BaseModel):
    """Prompts one essay can answer."""

    key: str
    label: str = Field(
        description="Short name of the shared theme in the UI language, stored."
    )
    kind: Literal["common", "shared", "unique"]
    category: Category = Field(
        description="What the prompts ask, derived on the server from the prompt "
        "text, the stored group label and the word limit."
    )
    short_answers: list[ShortAnswerOut] = Field(
        description="My short texts for member prompts; only for `short_answer`."
    )
    spread: float
    prompts: list[PromptRefOut]
    covered: bool = Field(description="An essay or slot already answers a member.")
    essay_ids: list[UUID] = Field(description="My essays targeting a member prompt.")
    in_list_count: int = Field(
        description="Universities on my list with a prompt in the group."
    )
    due_utc: dt.datetime | None = Field(
        description="Earliest application due date among those universities."
    )
    due_predicted: bool = Field(description="`due_utc` is predicted, not confirmed.")

    @classmethod
    def of(cls, g: GroupView, covered: frozenset[str]) -> "PromptGroupOut":
        """Build from a group view."""
        return cls(
            key=g.group.key,
            label=g.label,
            kind=g.group.kind,
            category=g.category,
            short_answers=[ShortAnswerOut.of(a) for a in g.short_answers],
            spread=g.group.spread,
            prompts=[PromptRefOut.of(p) for p in g.group.prompts],
            covered=any(p.key in covered for p in g.group.prompts),
            essay_ids=list(g.essay_ids),
            in_list_count=g.in_list_count,
            due_utc=g.due_utc,
            due_predicted=g.due_predicted,
        )


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
            groups=[PromptGroupOut.of(g, v.covered) for g in v.groups],
        )


class IdeaFitIn(BaseModel):
    """An idea text to match against the prompts."""

    text: str = Field(min_length=1, max_length=IDEA_MAX)
    cached_only: bool = Field(
        default=False,
        description="Return a stored fit only; `pending` when none exists.",
    )


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
    cached: bool = Field(description="Served from the store; no model was called.")
    pending: bool = Field(description="`cached_only` was set and nothing is stored.")

    @classmethod
    def of(cls, r: IdeaFit) -> "IdeaFitOut":
        """Build from the service result."""
        return cls(
            available=r.available,
            model=r.model,
            items=[PromptFitOut.of(f) for f in r.items],
            cached=r.cached,
            pending=r.pending,
        )


async def get_prompt_map(
    container: ContainerDep,
    ctx: AdmissionCtx,
    scope: Literal["list", "all"] = "all",
    lang: Lang = None,
) -> PromptMapOut:
    """The prompts grouped into named clusters; `scope=list` is my list + Common App."""
    view = await container.admission.essay_prompt_map.prompt_map(
        ctx, scope, _locale(lang)
    )
    return PromptMapOut.of(view)


async def fit_idea(
    body: IdeaFitIn, container: ContainerDep, ctx: AdmissionCtx
) -> IdeaFitOut:
    """Score an idea against the prompts no essay or slot covers (AI consent)."""
    fit = await container.admission.essay_prompt_map.fit(
        ctx, body.text, cached_only=body.cached_only
    )
    return IdeaFitOut.of(fit)


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
