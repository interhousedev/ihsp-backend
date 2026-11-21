"""Fit preferences, professions and ikigai (`/v1/admission/me/*`, `/professions`)."""

import datetime as dt
from typing import Annotated
from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.fit_preferences import FitPreferences
from app.modules.admission.application.professions import MyProfession
from app.modules.admission.domain.fit import RATING_MAX, RATING_MIN
from app.modules.admission.domain.professions import (
    IKIGAI_ITEMS_MAX,
    MAJOR_GROUPS,
    PROFESSIONS_MAX,
    Ikigai,
    Profession,
)

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])
Lang = Annotated[str | None, Header(alias="Accept-Language")]


def _rating() -> int:
    return Field(default=5, ge=RATING_MIN, le=RATING_MAX)


class RatingsBody(BaseModel):
    """How much each thing matters, 1 (little) to 10 (a lot)."""

    price: int = _rating()
    salary: int = _rating()
    ai_resilience: int = _rating()
    prestige: int = _rating()
    academics: int = _rating()
    social: int = _rating()
    city: int = _rating()
    home: int = _rating()


class FitPreferencesIn(BaseModel):
    """The eight ratings the student saves."""

    ratings: RatingsBody


class AxisWeightsOut(BaseModel):
    """Weights of the four fit axes; they sum to 1."""

    afford: float
    goals: float
    profile: float
    traits: float


class FitPreferencesOut(BaseModel):
    """Saved ratings (defaults when never saved) and the weights they give."""

    ratings: RatingsBody
    weights: AxisWeightsOut
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, v: FitPreferences) -> "FitPreferencesOut":
        """Map the application result."""
        return cls(
            ratings=RatingsBody(**v.ratings),
            weights=AxisWeightsOut(**v.weights),
            updated_at=v.updated_at,
        )


class ProfessionSourceOut(BaseModel):
    """A cited source."""

    label: str
    url: str


class ProfessionOut(BaseModel):
    """An ISCO-08 occupation with its GenAI exposure."""

    id: str
    name: str
    group: str
    ai_exposure: float
    ai_risk: str
    horizon: str
    salary_band: str | None
    related_fields: list[str]
    sources: list[ProfessionSourceOut]

    @classmethod
    def of(cls, p: Profession, locale: str) -> "ProfessionOut":
        """Localise one profession."""
        groups = MAJOR_GROUPS[p.group]
        return cls(
            id=p.id,
            name=p.name(locale),
            group=groups.get(locale) or groups["ru"],
            ai_exposure=p.ai_exposure,
            ai_risk=p.ai_risk,
            horizon=p.horizon,
            salary_band=p.salary_band,
            related_fields=list(p.related_fields),
            sources=[ProfessionSourceOut(label=s.label, url=s.url) for s in p.sources],
        )


class MyProfessionOut(ProfessionOut):
    """A picked profession and its rank (1 = first choice)."""

    rank: int


class ProfessionListOut(BaseModel):
    """Search result."""

    items: list[ProfessionOut]


class MyProfessionListOut(BaseModel):
    """The caller's ranked picks."""

    items: list[MyProfessionOut]

    @classmethod
    def of(cls, rows: list[MyProfession], locale: str) -> "MyProfessionListOut":
        """Localise the picks."""
        return cls(
            items=[
                MyProfessionOut(
                    **ProfessionOut.of(r.profession, locale).model_dump(), rank=r.rank
                )
                for r in rows
            ]
        )


class ChosenIn(BaseModel):
    """One pick."""

    profession_id: str
    rank: int = Field(ge=1, le=PROFESSIONS_MAX)


class ChosenListIn(BaseModel):
    """At most five picks."""

    items: list[ChosenIn] = Field(max_length=PROFESSIONS_MAX)


class IkigaiBody(BaseModel):
    """Free-text chips of the four ikigai questions."""

    love: list[str] = Field(default_factory=list, max_length=IKIGAI_ITEMS_MAX)
    good_at: list[str] = Field(default_factory=list, max_length=IKIGAI_ITEMS_MAX)
    needs: list[str] = Field(default_factory=list, max_length=IKIGAI_ITEMS_MAX)
    paid: list[str] = Field(default_factory=list, max_length=IKIGAI_ITEMS_MAX)

    @classmethod
    def of(cls, v: Ikigai) -> "IkigaiBody":
        """Map the domain value."""
        return cls(
            love=list(v.love),
            good_at=list(v.good_at),
            needs=list(v.needs),
            paid=list(v.paid),
        )


async def get_fit_preferences(
    container: ContainerDep, ctx: StudentCtx
) -> FitPreferencesOut:
    """The caller's ratings and the axis weights they give."""
    return FitPreferencesOut.of(await container.admission.fit_preferences.get(ctx))


async def put_fit_preferences(
    body: FitPreferencesIn, container: ContainerDep, ctx: StudentCtx
) -> FitPreferencesOut:
    """Replace the caller's ratings."""
    saved = await container.admission.fit_preferences.put(
        ctx, body.ratings.model_dump()
    )
    return FitPreferencesOut.of(saved)


async def search_professions(
    container: ContainerDep,
    ctx: StudentCtx,
    accept_language: Lang = None,
    q: Annotated[str, Query(max_length=80)] = "",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
) -> ProfessionListOut:
    """Search professions by name in any language."""
    loc = _locale(accept_language)
    found = container.admission.professions.search(q, limit)
    return ProfessionListOut(items=[ProfessionOut.of(p, loc) for p in found])


async def get_my_professions(
    container: ContainerDep, ctx: StudentCtx, accept_language: Lang = None
) -> MyProfessionListOut:
    """The caller's ranked professions."""
    rows = await container.admission.professions.mine(ctx)
    return MyProfessionListOut.of(rows, _locale(accept_language))


async def put_my_professions(
    body: ChosenListIn,
    container: ContainerDep,
    ctx: StudentCtx,
    accept_language: Lang = None,
) -> MyProfessionListOut:
    """Replace the caller's ranked professions (at most five)."""
    rows = await container.admission.professions.choose(
        ctx, [(i.profession_id, i.rank) for i in body.items]
    )
    return MyProfessionListOut.of(rows, _locale(accept_language))


async def get_ikigai(container: ContainerDep, ctx: StudentCtx) -> IkigaiBody:
    """The caller's ikigai chips."""
    return IkigaiBody.of(await container.admission.professions.ikigai(ctx))


async def put_ikigai(
    body: IkigaiBody, container: ContainerDep, ctx: StudentCtx
) -> IkigaiBody:
    """Replace the caller's ikigai chips."""
    saved = await container.admission.professions.set_ikigai(ctx, body.model_dump())
    return IkigaiBody.of(saved)


class FitAnalysisAxisOut(BaseModel):
    """One axis before and after the AI correction."""

    key: str
    base_score: int | None
    score: int | None


class FitAnalysisOut(BaseModel):
    """The corrected fit ring of one university and a short text."""

    base_total: int | None
    total: int | None
    known_share: float
    axes: list[FitAnalysisAxisOut]
    strengths: list[str]
    risks: list[str]
    next_step: str
    ai: bool = Field(description="False without AI consent: rule-based values.")


async def post_fit_analysis(
    institution_id: UUID,
    container: ContainerDep,
    ctx: StudentCtx,
    accept_language: Lang = None,
) -> FitAnalysisOut:
    """A quick AI read of the caller's fit for one university (cached, limited)."""
    a = await container.admission.fit_analysis.analyse(
        ctx, institution_id, _locale(accept_language)
    )
    return FitAnalysisOut(
        base_total=a.base_total,
        total=a.total,
        known_share=a.known_share,
        axes=[
            FitAnalysisAxisOut(key=x.key, base_score=x.base_score, score=x.score)
            for x in a.axes
        ],
        strengths=list(a.strengths),
        risks=list(a.risks),
        next_step=a.next_step,
        ai=a.ai,
    )


router.add_api_route(
    "/fit/{institution_id}/analysis",
    post_fit_analysis,
    methods=["POST"],
    response_model=FitAnalysisOut,
    operation_id="admission_post_fit_analysis",
)
router.add_api_route(
    "/me/fit-preferences",
    get_fit_preferences,
    methods=["GET"],
    response_model=FitPreferencesOut,
    operation_id="admission_get_fit_preferences",
)
router.add_api_route(
    "/me/fit-preferences",
    put_fit_preferences,
    methods=["PUT"],
    response_model=FitPreferencesOut,
    operation_id="admission_put_fit_preferences",
)
router.add_api_route(
    "/professions",
    search_professions,
    methods=["GET"],
    response_model=ProfessionListOut,
    operation_id="admission_search_professions",
)
router.add_api_route(
    "/me/professions",
    get_my_professions,
    methods=["GET"],
    response_model=MyProfessionListOut,
    operation_id="admission_get_my_professions",
)
router.add_api_route(
    "/me/professions",
    put_my_professions,
    methods=["PUT"],
    response_model=MyProfessionListOut,
    operation_id="admission_put_my_professions",
)
router.add_api_route(
    "/me/ikigai",
    get_ikigai,
    methods=["GET"],
    response_model=IkigaiBody,
    operation_id="admission_get_ikigai",
)
router.add_api_route(
    "/me/ikigai",
    put_ikigai,
    methods=["PUT"],
    response_model=IkigaiBody,
    operation_id="admission_put_ikigai",
)
