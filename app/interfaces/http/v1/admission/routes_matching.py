"""Preferences, matches and swipe decisions (`/preferences`, `/matches`)."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_chooser import RankingOut, _description
from app.interfaces.http.v1.admission.routes_items import _locale
from app.interfaces.http.v1.admission.schemas_focuses import FocusOut, focuses_out
from app.modules.admission.application.matching import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MatchItem,
    PreferenceView,
)
from app.modules.admission.domain.admit_rate import intl_admission_rate
from app.modules.admission.domain.budget import estimated_aid
from app.modules.admission.domain.chooser import next_deadline_round
from app.modules.admission.domain.fit import FitResult
from app.modules.admission.domain.matching import (
    MAJOR_MAX,
    REGION_MAX,
    budget_fit,
)
from app.modules.admission.domain.matching import cost_usd as sticker_usd
from app.modules.admission.domain.rankings import (
    experience_meters,
    map_url,
    relevant_rankings,
)
from app.shared.clock import local_today

from fastapi import APIRouter, Header, Query, Response, status
from pydantic import AfterValidator, BaseModel, ConfigDict, Field, StringConstraints

router = APIRouter(prefix="/v1/admission", tags=["admission"])


def _unique(items: list[Any]) -> list[Any]:
    if len(set(items)) != len(items):
        raise ValueError("items must be unique")
    return items


_UniqueSettings = Annotated[
    list[Literal["rural", "suburban", "city"]],
    Field(max_length=3),
    AfterValidator(_unique),
]
"""Campus settings; an empty list means no preference."""
_UniqueRegions = Annotated[
    list[Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$")]],
    Field(max_length=REGION_MAX),
    AfterValidator(_unique),
]
"""ISO-3166 alpha-2 country codes; an empty list means anywhere."""


class PreferenceAnswersIO(BaseModel):
    """The answers of the questionnaire; every field is optional."""

    model_config = ConfigDict(extra="forbid")

    experience: Literal["academic", "social", "adventure", "holistic"] | None = None
    setting: _UniqueSettings | None = None
    region: _UniqueRegions | None = None
    small_classes: bool | None = None
    ec_important: bool | None = None
    food_important: bool | None = None
    major: str | None = Field(default=None, min_length=1, max_length=MAJOR_MAX)
    prestige: bool | None = None
    academics_first: bool | None = None
    need_aid: bool | None = None
    budget: Literal["under_10k", "under_30k", "under_50k", "any"] | None = None
    cost_major: bool | None = None


class PreferencesOut(BaseModel):
    """Stored answers, their tags and whether all 13 are answered."""

    answers: PreferenceAnswersIO
    tags: list[str]
    completed: bool
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, v: PreferenceView) -> "PreferencesOut":
        """Map the application result."""
        a = v.answers
        return cls(
            answers=PreferenceAnswersIO.model_validate(a, from_attributes=True),
            tags=v.tags,
            completed=v.completed,
            updated_at=v.updated_at,
        )


class OverlapOut(BaseModel):
    """Preference tags a university meets, out of those it can be judged on."""

    count: int
    total: int
    tags: list[str]


class NextDeadlineOut(BaseModel):
    """The soonest upcoming deadline and its round (plan code)."""

    date: dt.date
    round: str


class ExperienceOut(BaseModel):
    """One 1..5 rating of the campus experience with its short note."""

    key: Literal["social", "research", "work"]
    score: int = Field(ge=1, le=5)
    note: str | None = None


class MatchOut(BaseModel):
    """A university with its match for the caller."""

    university_id: UUID
    name: str
    city: str | None
    country: str
    logo_url: str | None
    cover_url: str | None
    institution_type: str | None
    admission_rate: float | None = Field(default=None, ge=0, le=1)
    cost_after_aid_usd: float | None
    match_pct: int = Field(ge=0, le=100)
    overlap: OverlapOut
    status: Literal["safety", "target", "reach"] | None
    fit_total: int | None = Field(default=None, ge=0, le=100)
    known_share: float | None = Field(default=None, ge=0, le=1)
    avg_aid_intl: float | None = Field(
        default=None, description="Average aid for international students, USD."
    )
    intl_acceptance_rate: float | None = Field(default=None, ge=0, le=1)
    meets_full_need: bool | None = None
    next_deadline: NextDeadlineOut | None = None
    description: str | None = Field(
        default=None, description="In the request language, else English."
    )
    fields: list[str] = []
    rankings: list[RankingOut] = Field(
        default=[], description="At most two, relevant to the student; else empty."
    )
    cost_usd: float | None = Field(default=None, description="Yearly sticker price.")
    net_cost_usd: float | None = Field(
        default=None, description="Sticker price minus the average aid, an estimate."
    )
    aid_estimate_usd: float | None = None
    budget_fit: Literal["fits", "above"] | None = Field(
        default=None,
        description="Net (else sticker) price against the student's budget; "
        "null when the budget or the price is unknown.",
    )
    experience: list[ExperienceOut] = []
    focuses: list[FocusOut] = Field(
        default=[],
        description="What the university says it looks for; verified items only.",
    )
    map_url: str

    @classmethod
    def of(
        cls,
        m: MatchItem,
        fit: FitResult | None = None,
        *,
        today: dt.date,
        locale: str = "en",
        subjects: tuple[str, ...] = (),
        maps_template: str | None = None,
        budget_band: str | None = None,
    ) -> "MatchOut":
        """Map the application result."""
        i = m.institution
        aid = i.aid_profile
        gross = sticker_usd(i)
        if gross is None:
            fact = i.fact("intl_coa_usd")
            val = fact.value if fact and isinstance(fact.value, dict) else {}
            raw = val.get("value")
            if (
                val.get("currency", "USD") == "USD"
                and isinstance(raw, int | float)
                and not isinstance(raw, bool)
                and raw > 0
            ):
                gross = Decimal(str(raw))
        aid_usd = estimated_aid(gross, "USD", aid) if gross is not None else None
        ranks = i.fact("rankings")
        exp = i.fact("experience_scores")
        link = i.fact("map_url")
        return cls(
            university_id=i.id,
            name=i.name,
            city=i.city,
            country=i.country,
            logo_url=i.logo_url,
            cover_url=i.cover_url,
            institution_type=(
                str(kind.value) if (kind := i.fact("institution_type")) else None
            ),
            admission_rate=m.admission_rate,
            cost_after_aid_usd=(
                float(m.cost_after_aid_usd)
                if m.cost_after_aid_usd is not None
                else None
            ),
            match_pct=m.match_pct,
            overlap=OverlapOut(
                count=m.overlap.count, total=m.overlap.total, tags=list(m.overlap.tags)
            ),
            status=m.status,
            fit_total=fit.total if fit is not None else None,
            known_share=fit.known_share if fit is not None else None,
            avg_aid_intl=(
                float(aid.avg_aid)
                if aid is not None
                and aid.avg_aid is not None
                and aid.avg_aid_scope == "intl"
                else None
            ),
            intl_acceptance_rate=intl_admission_rate(i),
            meets_full_need=aid.meets_full_need if aid is not None else None,
            next_deadline=(
                NextDeadlineOut(date=due[0], round=due[1])
                if (due := next_deadline_round(i, today)) is not None
                else None
            ),
            description=_description(i.description, locale),
            fields=i.fields,
            rankings=[
                RankingOut(**r)
                for r in relevant_rankings(ranks.value if ranks else None, subjects)
            ],
            cost_usd=float(gross) if gross is not None else None,
            net_cost_usd=(
                float(gross - aid_usd)
                if gross is not None and aid_usd is not None
                else None
            ),
            aid_estimate_usd=float(aid_usd) if aid_usd is not None else None,
            budget_fit=budget_fit(
                budget_band,
                gross - aid_usd if gross is not None and aid_usd is not None else None,
                gross,
            ),
            focuses=focuses_out(i, locale),
            experience=[
                ExperienceOut(**x)
                for x in experience_meters(exp.value if exp else None, locale)
            ],
            map_url=map_url(
                i.name,
                i.city,
                i.country,
                override=str(link.value) if link else None,
                template=maps_template,
            ),
        )


class MatchListOut(BaseModel):
    """Undecided universities, best match first."""

    items: list[MatchOut]
    undecided_only: bool = True


class DecisionIn(BaseModel):
    """A swipe."""

    model_config = ConfigDict(extra="forbid")

    decision: Literal["interested", "not_my_vibe"]


async def get_preferences(container: ContainerDep, ctx: AdmissionCtx) -> PreferencesOut:
    """The caller's questionnaire answers."""
    return PreferencesOut.of(await container.admission.matching.preferences(ctx))


async def put_preferences(
    body: PreferenceAnswersIO, container: ContainerDep, ctx: AdmissionCtx
) -> PreferencesOut:
    """Save the sent answers; omitted ones stay as they were."""
    patch = body.model_dump(exclude_unset=True)
    return PreferencesOut.of(
        await container.admission.matching.save_preferences(ctx, patch)
    )


async def list_matches(
    container: ContainerDep,
    ctx: AdmissionCtx,
    limit: int = Query(default=DEFAULT_LIMIT, ge=1, le=MAX_LIMIT),
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> MatchListOut:
    """Universities not yet decided on, ranked by the caller's preferences."""
    rows = await container.admission.matching.matches(ctx, limit)
    return await _list_out(container, ctx, rows, accept_language)


async def list_dismissed(
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: Annotated[str | None, Header(alias="Accept-Language")] = None,
) -> MatchListOut:
    """Universities the caller marked "not my vibe"; Return is the DELETE decision."""
    rows = await container.admission.matching.dismissed(ctx)
    out = await _list_out(container, ctx, rows, accept_language)
    return out.model_copy(update={"undecided_only": False})


async def _list_out(
    container: ContainerDep,
    ctx: AdmissionCtx,
    rows: list[MatchItem],
    accept_language: str | None,
) -> MatchListOut:
    fits = await container.admission.fit.fits_for(
        ctx,
        [m.institution for m in rows],
        _locale(accept_language),
        container.clock.now().year,
    )
    today = local_today(container.clock)
    locale = _locale(accept_language)
    subjects = await container.admission.fit.ranking_subjects(ctx)
    template = await container.admission.maps_settings.get()
    band = await container.admission.fit.budget_band(ctx)
    return MatchListOut(
        items=[
            MatchOut.of(
                m,
                fits.get(m.institution.id),
                today=today,
                locale=locale,
                subjects=subjects,
                maps_template=template,
                budget_band=band,
            )
            for m in rows
        ]
    )


async def decide(
    university_id: UUID, body: DecisionIn, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Swipe a university; `interested` adds it to the caller's list."""
    await container.admission.matching.decide(ctx, university_id, body.decision)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def undo_decision(
    university_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Undo a swipe."""
    await container.admission.matching.undo(ctx, university_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


router.add_api_route(
    "/preferences",
    get_preferences,
    methods=["GET"],
    response_model=PreferencesOut,
    operation_id="admission_get_preferences",
)
router.add_api_route(
    "/preferences",
    put_preferences,
    methods=["PUT"],
    response_model=PreferencesOut,
    operation_id="admission_put_preferences",
)
router.add_api_route(
    "/matches",
    list_matches,
    methods=["GET"],
    response_model=MatchListOut,
    operation_id="admission_list_matches",
)
router.add_api_route(
    "/matches/dismissed",
    list_dismissed,
    methods=["GET"],
    response_model=MatchListOut,
    operation_id="admission_list_dismissed_matches",
)
router.add_api_route(
    "/matches/{university_id}/decision",
    decide,
    methods=["POST"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_decide_match",
)
router.add_api_route(
    "/matches/{university_id}/decision",
    undo_decision,
    methods=["DELETE"],
    status_code=status.HTTP_204_NO_CONTENT,
    operation_id="admission_undo_match_decision",
)
