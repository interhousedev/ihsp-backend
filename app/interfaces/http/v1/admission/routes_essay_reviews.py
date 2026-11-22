"""Essay review routes (`/v1/admission/essays/{essay_id}/reviews`)."""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.essay_reviews import EssayReviews, UniEntry
from app.modules.admission.domain.essay_reviews import (
    MAX_UNIVERSITIES,
    BaseReview,
    UniReview,
)

from fastapi import APIRouter, Header
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]


class EssayReviewsIn(BaseModel):
    """The universities to review the essay for; `refresh` ignores stored results."""

    institution_ids: list[UUID] = Field(
        default_factory=list, max_length=MAX_UNIVERSITIES
    )
    refresh: bool = False


class DimensionScoreOut(BaseModel):
    """One rubric dimension scored 0 to 5 with a verbatim quote."""

    key: str
    score: int
    quote: str | None
    comment: str


class ParagraphNoteOut(BaseModel):
    """A note on one paragraph; `paragraph` is 1-based."""

    paragraph: int
    note: str


class ExemplarPatternOut(BaseModel):
    """A pattern of a published exemplar the draft could use."""

    exemplar_id: UUID
    title: str
    school_name: str
    source_url: str
    pattern: str


class BaseReviewOut(BaseModel):
    """The review of the writing; the same for every university."""

    score: int
    band: str
    dimensions: list[DimensionScoreOut]
    summary: str
    strengths: list[str]
    improvements: list[str]
    paragraphs: list[ParagraphNoteOut]
    patterns: list[ExemplarPatternOut]
    word_count: int
    word_limit: int | None
    over_limit: bool
    generic: bool

    @classmethod
    def of(cls, b: BaseReview) -> "BaseReviewOut":
        """Map the domain review."""
        return cls(
            score=b.score,
            band=b.band,
            dimensions=[
                DimensionScoreOut(
                    key=d.key, score=d.score, quote=d.quote, comment=d.comment
                )
                for d in b.dimensions
            ],
            summary=b.summary,
            strengths=list(b.strengths),
            improvements=list(b.improvements),
            paragraphs=[
                ParagraphNoteOut(paragraph=p.paragraph, note=p.note)
                for p in b.paragraphs
            ],
            patterns=[
                ExemplarPatternOut(
                    exemplar_id=p.exemplar_id,
                    title=p.title,
                    school_name=p.school_name,
                    source_url=p.source_url,
                    pattern=p.pattern,
                )
                for p in b.patterns
            ],
            word_count=b.word_count,
            word_limit=b.word_limit,
            over_limit=b.over_limit,
            generic=b.generic,
        )


class GoalAlignmentOut(BaseModel):
    """How the essay meets one sourced goal of the university."""

    key: str
    goal: str
    source_url: str | None
    alignment: Literal["strong", "partial", "missing"]
    evidence: str | None
    suggestion: str


class AoReactionOut(BaseModel):
    """How an admissions officer of the university may react (patterns only)."""

    summary: str
    likely_positive: list[str]
    likely_concerns: list[str]


class UniReviewOut(BaseModel):
    """The fit with one university; `alignment` is 0 to 100."""

    alignment: int
    goals: list[GoalAlignmentOut]
    fit_summary: str
    supplement_tips: list[str]
    risks: list[str]
    sourced: bool
    ao_reaction: AoReactionOut | None = None

    @classmethod
    def of(cls, u: UniReview) -> "UniReviewOut":
        """Map the domain review."""
        return cls(
            alignment=u.alignment,
            goals=[
                GoalAlignmentOut(
                    key=g.key,
                    goal=g.goal,
                    source_url=g.source_url,
                    alignment=g.alignment,
                    evidence=g.evidence,
                    suggestion=g.suggestion,
                )
                for g in u.goals
            ],
            fit_summary=u.fit_summary,
            supplement_tips=list(u.supplement_tips),
            risks=list(u.risks),
            sourced=u.sourced,
            ao_reaction=(
                None
                if u.ao_reaction is None
                else AoReactionOut(
                    summary=u.ao_reaction.summary,
                    likely_positive=list(u.ao_reaction.likely_positive),
                    likely_concerns=list(u.ao_reaction.likely_concerns),
                )
            ),
        )


class UniEntryOut(BaseModel):
    """The review for one university; `stale` when the essay changed since."""

    institution_id: UUID
    name: str
    cached: bool
    stale: bool
    review: UniReviewOut

    @classmethod
    def of(cls, e: UniEntry) -> "UniEntryOut":
        """Map the service entry."""
        return cls(
            institution_id=e.institution_id,
            name=e.name,
            cached=e.cached,
            stale=e.stale,
            review=UniReviewOut.of(e.review),
        )


class EssayReviewsOut(BaseModel):
    """The base review (null before the first run) and the university reviews."""

    base: BaseReviewOut | None
    base_cached: bool
    base_stale: bool
    universities: list[UniEntryOut]

    @classmethod
    def of(cls, r: EssayReviews) -> "EssayReviewsOut":
        """Map the service result."""
        return cls(
            base=None if r.base is None else BaseReviewOut.of(r.base),
            base_cached=r.base_cached,
            base_stale=r.base_stale,
            universities=[UniEntryOut.of(e) for e in r.universities],
        )


async def run_reviews(
    essay_id: UUID,
    body: EssayReviewsIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    lang: Lang = None,
) -> EssayReviewsOut:
    """Review my essay and its fit with up to 5 universities (AI consent, limit)."""
    r = await container.admission.essay_reviews.run(
        ctx,
        essay_id,
        body.institution_ids,
        refresh=body.refresh,
        locale=_locale(lang),
    )
    return EssayReviewsOut.of(r)


async def get_reviews(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx, lang: Lang = None
) -> EssayReviewsOut:
    """My stored essay reviews, marked stale when the essay changed; no model call."""
    r = await container.admission.essay_reviews.get(ctx, essay_id, _locale(lang))
    return EssayReviewsOut.of(r)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_FORBIDDEN = {
    403: {"model": ProblemOut, "description": "Not the owner, or no AI consent."}
}
_NOT_FOUND = {
    404: {"model": ProblemOut, "description": "Not my essay or no such university."}
}
_INVALID = {
    422: {
        "model": ProblemOut,
        "description": "More than 5 universities, or the essay has under 50 words.",
    }
}
_LIMITED = {429: {"model": ProblemOut, "description": "The weekly limit is used up."}}
_SEALED = {503: {"model": ProblemOut, "description": "The essay key service is down."}}
_PATH = "/essays/{essay_id}/reviews"

_route(
    _PATH,
    run_reviews,
    "POST",
    "run_essay_reviews",
    response_model=EssayReviewsOut,
    responses={**_FORBIDDEN, **_NOT_FOUND, **_INVALID, **_LIMITED, **_SEALED},
)
_route(
    _PATH,
    get_reviews,
    "GET",
    "get_essay_reviews",
    response_model=EssayReviewsOut,
    responses={**_FORBIDDEN, **_NOT_FOUND, **_SEALED},
)
