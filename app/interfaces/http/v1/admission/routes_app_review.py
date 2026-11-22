"""Full application review routes (`/v1/admission/me/application-reviews*`).

The student starts and reads the versions of their own review; a counselor or
an administrator with the student in scope reads only the versions built from
shared material (mentors never).
"""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.domain.app_review import AppReview

from fastapi import APIRouter, Header, status
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admission", tags=["admission"])

SectionKeyOut = Literal[
    "profile",
    "activities",
    "alignment",
    "essays",
    "academics",
    "universities",
    "readiness",
]


class ReviewLinkOut(BaseModel):
    """The screen a finding or subsection opens; `ref` is empty for a whole screen."""

    kind: Literal[
        "profile",
        "activities",
        "honors",
        "essay",
        "list_entry",
        "survey",
        "grades",
        "tests",
        "recommendations",
        "none",
    ] = "none"
    ref: str = ""


class ReviewFindingOut(BaseModel):
    """One finding of a section with the references of its evidence."""

    kind: Literal["strength", "risk", "gap"]
    text: str
    evidence: list[str]
    link: ReviewLinkOut = ReviewLinkOut()


class ReviewSubsectionOut(BaseModel):
    """One real part of a section (an essay, an activity, a list entry...)."""

    key: str
    title: str
    verdict: Literal["strong", "mixed", "weak", "missing"]
    ao_view: str = ""
    finding_indexes: list[int] = []
    link: ReviewLinkOut = ReviewLinkOut()


class ReviewSectionOut(BaseModel):
    """One section agent's report; `pending`/`running` until it finishes."""

    key: SectionKeyOut
    status: Literal["pending", "running", "done", "failed", "skipped"]
    score: int | None = None
    summary: str = ""
    ao_view: str = ""
    subsections: list[ReviewSubsectionOut] = []
    findings: list[ReviewFindingOut] = []
    next_actions: list[str] = []


class ReviewPointOut(BaseModel):
    """A strength or a risk of the merged report."""

    text: str
    section: SectionKeyOut
    evidence: list[str]


class ReviewActionOut(BaseModel):
    """A prioritized next action (1 is the most urgent)."""

    title: str
    why: str
    section: SectionKeyOut
    priority: int


class ReviewScoreOut(BaseModel):
    """The score of one section, 0 to 10."""

    section: SectionKeyOut
    score: int
    comment: str


class ReviewSpikeOut(BaseModel):
    """How coherent the application's spike is, 0 to 10."""

    score: int
    comment: str


class ReviewReportOut(BaseModel):
    """The lead's merged report; `fallback` when merged without the lead model."""

    headline: str
    overall_score: int
    strengths: list[ReviewPointOut]
    risks: list[ReviewPointOut]
    spike: ReviewSpikeOut
    next_actions: list[ReviewActionOut]
    section_scores: list[ReviewScoreOut]
    injection_suspected: bool
    fallback: bool


class AppReviewOut(BaseModel):
    """One version of the full application review."""

    id: UUID
    version: int
    status: Literal["queued", "running", "done", "failed"]
    locale: str
    created_at: dt.datetime
    started_at: dt.datetime | None
    finished_at: dt.datetime | None
    error_code: str | None
    sections: list[ReviewSectionOut]
    report: ReviewReportOut | None

    @classmethod
    def of(cls, r: AppReview) -> "AppReviewOut":
        """Map the domain review."""
        report: Any = r.report
        return cls(
            id=r.id,
            version=r.version,
            status=r.status,
            locale=r.locale,
            created_at=r.created_at,
            started_at=r.started_at,
            finished_at=r.finished_at,
            error_code=r.error_code,
            sections=[ReviewSectionOut.model_validate(s) for s in r.section_states()],
            report=ReviewReportOut.model_validate(report) if report else None,
        )


class AppReviewListOut(BaseModel):
    """The review versions, newest first."""

    items: list[AppReviewOut]


Lang = Annotated[str | None, Header(alias="Accept-Language")]


async def start_app_review(
    container: ContainerDep, ctx: StudentCtx, accept_language: Lang = None
) -> AppReviewOut:
    """Queue a new review (AI consent and a weekly limit apply)."""
    review = await container.admission.app_review.start(ctx, _locale(accept_language))
    return AppReviewOut.of(review)


async def list_app_reviews(
    container: ContainerDep, ctx: StudentCtx
) -> AppReviewListOut:
    """My review versions."""
    rows = await container.admission.app_review.list_mine(ctx)
    return AppReviewListOut(items=[AppReviewOut.of(r) for r in rows])


async def get_app_review(
    review_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> AppReviewOut:
    """One of my review versions (poll while queued or running)."""
    return AppReviewOut.of(
        await container.admission.app_review.get_mine(ctx, review_id)
    )


async def list_student_app_reviews(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> AppReviewListOut:
    """A student's staff-visible reviews (counselors and administrators)."""
    rows = await container.admission.app_review.staff_list(ctx, student_id)
    return AppReviewListOut(items=[AppReviewOut.of(r) for r in rows])


async def get_student_app_review(
    student_id: UUID, review_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> AppReviewOut:
    """One staff-visible review of a student."""
    review = await container.admission.app_review.staff_get(ctx, student_id, review_id)
    return AppReviewOut.of(review)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route(
    "/me/application-reviews",
    start_app_review,
    "POST",
    "start_app_review",
    response_model=AppReviewOut,
    status_code=status.HTTP_202_ACCEPTED,
)
_route(
    "/me/application-reviews",
    list_app_reviews,
    "GET",
    "list_app_reviews",
    response_model=AppReviewListOut,
)
_route(
    "/me/application-reviews/{review_id}",
    get_app_review,
    "GET",
    "get_app_review",
    response_model=AppReviewOut,
)
_route(
    "/students/{student_id}/application-reviews",
    list_student_app_reviews,
    "GET",
    "list_student_app_reviews",
    response_model=AppReviewListOut,
)
_route(
    "/students/{student_id}/application-reviews/{review_id}",
    get_student_app_review,
    "GET",
    "get_student_app_review",
    response_model=AppReviewOut,
)
