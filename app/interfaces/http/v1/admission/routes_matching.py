"""Preferences, matches and swipe decisions (`/preferences`, `/matches`)."""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.application.matching import (
    DEFAULT_LIMIT,
    MAX_LIMIT,
    MatchItem,
    PreferenceView,
)
from app.modules.admission.domain.matching import MAJOR_MAX, REGION_MAX

from fastapi import APIRouter, Query, Response, status
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

    @classmethod
    def of(cls, m: MatchItem) -> "MatchOut":
        """Map the application result."""
        i = m.institution
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
) -> MatchListOut:
    """Universities not yet decided on, ranked by the caller's preferences."""
    rows = await container.admission.matching.matches(ctx, limit)
    return MatchListOut(items=[MatchOut.of(m) for m in rows])


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
