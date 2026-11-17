"""Activities, honors, metrics, interview and item review routes (§9, §13)."""

import datetime as dt
from decimal import Decimal
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.modules.admission.application.interview import InterviewState
from app.modules.admission.application.items import ItemView, MetricDraft
from app.modules.admission.application.review import NOTE_MAX
from app.modules.admission.application.review_prompts import LANGUAGES
from app.modules.admission.domain.items import Item, ItemGrade
from app.modules.admission.ports.items import Metric, StoredReview

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, ConfigDict, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

LocaleHeader = Annotated[str | None, Header(alias="Accept-Language")]
Grade = Literal[9, 10, 11, 12, 13]
Timing = Literal["school_year", "school_break", "all_year"]


def _locale(header: str | None) -> str:
    """Pick the first supported language of Accept-Language (default en)."""
    for part in (header or "").split(","):
        code = part.split(";")[0].strip().lower()[:2]
        if code in LANGUAGES:
            return code
    return "en"


class MetricIn(BaseModel):
    """A number of an item; `projected` requires `target_date`."""

    model_config = ConfigDict(extra="forbid")

    label: str = Field(max_length=80)
    value: Decimal
    unit: str | None = Field(default=None, max_length=24)
    horizon: Literal["current", "projected"] = "current"
    as_of: dt.date | None = None
    target_date: dt.date | None = None

    def draft(self) -> MetricDraft:
        """Map to the application draft."""
        return MetricDraft(**self.model_dump())


class MetricOut(BaseModel):
    """A stored metric."""

    id: UUID
    label: str
    value: Decimal
    unit: str | None
    horizon: str
    as_of: dt.date | None
    target_date: dt.date | None
    provenance: str

    @classmethod
    def of(cls, m: Metric) -> "MetricOut":
        """Map the metric."""
        return cls(
            id=m.id,
            label=m.label,
            value=m.value,
            unit=m.unit,
            horizon=m.horizon,
            as_of=m.as_of,
            target_date=m.target_date,
            provenance=m.provenance,
        )


class ReviewOut(BaseModel):
    """An item review: grades per dimension and the advice payload."""

    id: UUID
    target_id: UUID
    grades: dict[str, Any]
    overall: str | None
    payload: dict[str, Any]
    safety_flag: str
    status: str
    created_at: dt.datetime | None

    @classmethod
    def of(cls, r: StoredReview) -> "ReviewOut":
        """Map the stored review."""
        return cls(
            id=r.id,
            target_id=r.target_id,
            grades=r.grades,
            overall=r.overall,
            payload=r.payload,
            safety_flag=r.safety_flag,
            status=r.status,
            created_at=r.created_at,
        )


class ItemGradeOut(BaseModel):
    """An A-E grade with a one-line tip for the title and the description."""

    title_grade: str
    title_tip: str
    description_grade: str
    description_tip: str
    model: str

    @classmethod
    def of(cls, g: ItemGrade) -> "ItemGradeOut":
        """Map the stored grade."""
        return cls(
            title_grade=g.title_grade,
            title_tip=g.title_tip,
            description_grade=g.description_grade,
            description_tip=g.description_tip,
            model=g.model,
        )


class ItemOut(BaseModel):
    """An activity or honor with metrics and its newest review."""

    id: UUID
    student_id: UUID
    kind: str
    title: str
    organization: str
    description: str
    category: str | None
    grades: list[int]
    hours_per_week: int | None
    weeks_per_year: int | None
    position: int
    status: str
    timing: list[str]
    intend_in_college: bool | None
    lock_version: int
    metrics: list[MetricOut]
    review: ReviewOut | None
    review_stale: bool
    grade: ItemGradeOut | None
    grade_stale: bool

    @classmethod
    def of(cls, v: ItemView) -> "ItemOut":
        """Map the view."""
        i = v.item
        return cls(
            id=i.id,
            student_id=i.student_id,
            kind=i.kind,
            title=i.title,
            organization=i.organization,
            description=i.description,
            category=i.category,
            grades=list(i.grades),
            hours_per_week=i.hours_per_week,
            weeks_per_year=i.weeks_per_year,
            position=i.position,
            status=i.status,
            timing=list(i.timing),
            intend_in_college=i.intend_in_college,
            lock_version=i.lock_version,
            metrics=[MetricOut.of(m) for m in v.metrics],
            review=ReviewOut.of(v.review) if v.review else None,
            review_stale=v.stale,
            grade=ItemGradeOut.of(i.grade) if i.grade else None,
            grade_stale=i.grade_stale,
        )


class ItemListOut(BaseModel):
    """The student's items (one page: at most 15)."""

    items: list[ItemOut]
    next_cursor: str | None = None


class ItemCreateIn(BaseModel):
    """A new activity or honor; the limits are checked by the service."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["activity", "honor"]
    title: str
    organization: str = ""
    description: str = ""
    category: str | None = Field(default=None, max_length=40)
    grades: list[Grade] = Field(default_factory=list, max_length=5)
    hours_per_week: int | None = Field(default=None, ge=0, le=168)
    weeks_per_year: int | None = Field(default=None, ge=0, le=52)
    status: Literal["draft", "ready"] = "draft"
    timing: list[Timing] = Field(default_factory=list, max_length=3)
    intend_in_college: bool | None = None
    metrics: list[MetricIn] = Field(default_factory=list)


class ItemPatchIn(BaseModel):
    """Changed fields; `lock_version` is the one the client read."""

    model_config = ConfigDict(extra="forbid")

    lock_version: int
    title: str | None = None
    organization: str | None = None
    description: str | None = None
    category: str | None = Field(default=None, max_length=40)
    grades: list[Grade] | None = Field(default=None, max_length=5)
    hours_per_week: int | None = Field(default=None, ge=0, le=168)
    weeks_per_year: int | None = Field(default=None, ge=0, le=52)
    status: Literal["draft", "ready"] | None = None
    timing: list[Timing] | None = Field(default=None, max_length=3)
    intend_in_college: bool | None = None


class ItemOrderIn(BaseModel):
    """The item ids in their new display order."""

    model_config = ConfigDict(extra="forbid")

    ids: list[UUID] = Field(max_length=15)


class MetricsIn(BaseModel):
    """The full new set of an item's metrics."""

    model_config = ConfigDict(extra="forbid")

    metrics: list[MetricIn] = Field(max_length=8)


class MetricsOut(BaseModel):
    """The stored metrics."""

    items: list[MetricOut]
    next_cursor: str | None = None


class InterviewIn(BaseModel):
    """Answers to the last round keyed by question index; `restart` clears."""

    model_config = ConfigDict(extra="forbid")

    answers: dict[str, str] = Field(default_factory=dict)
    restart: bool = False


class InterviewRoundOut(BaseModel):
    """One round with its questions and answers."""

    round: int
    questions: list[dict[str, Any]]
    answers: dict[str, Any]


class InterviewOut(BaseModel):
    """The interview so far and, once ready, the proposed description."""

    item_id: UUID
    rounds: list[InterviewRoundOut]
    ready: bool
    proposal: dict[str, Any] | None
    safeguarding: bool

    @classmethod
    def of(cls, s: InterviewState) -> "InterviewOut":
        """Map the state."""
        return cls(
            item_id=s.item_id,
            rounds=[
                InterviewRoundOut(
                    round=r.round,
                    questions=list(r.questions.get("questions", [])),
                    answers=r.answers,
                )
                for r in s.rounds
            ],
            ready=s.ready,
            proposal=s.proposal,
            safeguarding=s.safeguarding,
        )


class FeedbackIn(BaseModel):
    """The student's reaction to a review."""

    model_config = ConfigDict(extra="forbid")

    kind: Literal["unfair", "helpful"]
    note: str | None = Field(default=None, max_length=NOTE_MAX)


async def list_my_items(container: ContainerDep, ctx: AdmissionCtx) -> ItemListOut:
    """Return my activities and honors."""
    views = await container.admission.items.list_items(ctx, ctx.user_id)
    return ItemListOut(items=[ItemOut.of(v) for v in views])


async def list_student_items(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> ItemListOut:
    """Return a student's activities and honors (staff and helpers in scope)."""
    views = await container.admission.items.list_items(ctx, student_id)
    return ItemListOut(items=[ItemOut.of(v) for v in views])


async def create_item(
    body: ItemCreateIn, container: ContainerDep, ctx: AdmissionCtx
) -> ItemOut:
    """Add an activity or honor at the end of its list."""
    item = Item(
        id=ctx.user_id,
        student_id=ctx.user_id,
        kind=body.kind,
        title=body.title,
        organization=body.organization,
        description=body.description,
        category=body.category,
        grades=tuple(body.grades),
        hours_per_week=body.hours_per_week,
        weeks_per_year=body.weeks_per_year,
        status=body.status,
        timing=tuple(body.timing),
        intend_in_college=body.intend_in_college,
    )
    view = await container.admission.items.create(
        ctx, item, [m.draft() for m in body.metrics]
    )
    return ItemOut.of(view)


async def patch_item(
    item_id: UUID, body: ItemPatchIn, container: ContainerDep, ctx: AdmissionCtx
) -> ItemOut:
    """Change fields of my item."""
    changes = body.model_dump(exclude_unset=True, exclude={"lock_version"})
    if "grades" in changes and changes["grades"] is not None:
        changes["grades"] = tuple(changes["grades"])
    if "timing" in changes:
        changes["timing"] = tuple(changes["timing"] or ())
    if changes.get("status") is None:
        changes.pop("status", None)
    for key in ("title", "organization", "description"):
        if key in changes and changes[key] is None:
            changes[key] = ""
    await container.admission.items.update(ctx, item_id, changes, body.lock_version)
    return await _one(container, ctx, item_id)


async def delete_item(
    item_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Delete my item with its metrics, interview and reviews."""
    await container.admission.items.delete(ctx, item_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def order_items(
    body: ItemOrderIn, container: ContainerDep, ctx: AdmissionCtx
) -> ItemListOut:
    """Set the display order of my items."""
    await container.admission.items.order(ctx, body.ids)
    return await list_my_items(container, ctx)


async def put_metrics(
    item_id: UUID, body: MetricsIn, container: ContainerDep, ctx: AdmissionCtx
) -> MetricsOut:
    """Replace the metrics of my item."""
    rows = await container.admission.items.set_metrics(
        ctx, item_id, [m.draft() for m in body.metrics]
    )
    return MetricsOut(items=[MetricOut.of(m) for m in rows])


async def get_interview(
    item_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> InterviewOut:
    """Return the interview of my item so far."""
    return InterviewOut.of(await container.admission.item_interviews.get(ctx, item_id))


async def step_interview(
    item_id: UUID,
    body: InterviewIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: LocaleHeader = None,
) -> InterviewOut:
    """Answer the last round and get the next one or the proposal."""
    state = await container.admission.item_interviews.step(
        ctx, item_id, body.answers, _locale(accept_language), restart=body.restart
    )
    return InterviewOut.of(state)


async def review_item(
    item_id: UUID,
    container: ContainerDep,
    ctx: AdmissionCtx,
    accept_language: LocaleHeader = None,
) -> ReviewOut:
    """Review my item (cached per input; soft daily limits)."""
    review = await container.admission.item_reviews.review(
        ctx, item_id, _locale(accept_language)
    )
    return ReviewOut.of(review)


async def review_feedback(
    review_id: UUID, body: FeedbackIn, container: ContainerDep, ctx: AdmissionCtx
) -> Response:
    """Mark my review as helpful or unfair."""
    await container.admission.item_reviews.feedback(
        ctx, review_id, body.kind, body.note
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def _one(container: ContainerDep, ctx: AdmissionCtx, item_id: UUID) -> ItemOut:
    views = await container.admission.items.list_items(ctx, ctx.user_id)
    return ItemOut.of(next(v for v in views if v.item.id == item_id))


_OK = status.HTTP_200_OK
_NO = status.HTTP_204_NO_CONTENT

for _path, _fn, _method, _model, _op, _code in (
    ("/me/items", list_my_items, "GET", ItemListOut, "admission_list_my_items", _OK),
    ("/me/items", create_item, "POST", ItemOut, "admission_create_item", 201),
    ("/me/items/order", order_items, "PUT", ItemListOut, "admission_order_items", _OK),
    ("/me/items/{item_id}", patch_item, "PATCH", ItemOut, "admission_patch_item", _OK),
    ("/me/items/{item_id}", delete_item, "DELETE", None, "admission_delete_item", _NO),
    (
        "/me/items/{item_id}/metrics",
        put_metrics,
        "PUT",
        MetricsOut,
        "admission_put_item_metrics",
        _OK,
    ),
    (
        "/me/items/{item_id}/interview",
        get_interview,
        "GET",
        InterviewOut,
        "admission_get_item_interview",
        _OK,
    ),
    (
        "/me/items/{item_id}/interview",
        step_interview,
        "POST",
        InterviewOut,
        "admission_step_item_interview",
        _OK,
    ),
    (
        "/me/items/{item_id}/review",
        review_item,
        "POST",
        ReviewOut,
        "admission_review_item",
        _OK,
    ),
    (
        "/me/reviews/{review_id}/feedback",
        review_feedback,
        "POST",
        None,
        "admission_review_feedback",
        _NO,
    ),
    (
        "/students/{student_id}/items",
        list_student_items,
        "GET",
        ItemListOut,
        "admission_list_student_items",
        _OK,
    ),
):
    router.add_api_route(
        _path,
        _fn,
        methods=[_method],
        response_model=_model,
        operation_id=_op,
        status_code=_code,
    )
