"""List planning routes: reach/target/safety classification, balance, AI ideas.

`GET /v1/admission/list/insights` classifies the entries of a list the caller
may read; `POST /v1/admission/list/suggest` asks the model for institutions to
add to the caller's own list (AI consent and a weekly limit apply).
"""

from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale

from fastapi import APIRouter, Header, Query
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Label = Literal["reach", "target", "safety"]
Lang = Annotated[str | None, Header(alias="Accept-Language")]


class ClassificationOut(BaseModel):
    """`effective` is what the UI shows; `source` says who decided it.

    `reasons` are stable codes (rate_target, gpa_low, test_required_missing,
    english_missing, gpa_strong, no_rate) that the web translates.
    """

    computed: Label | None
    effective: Label | None
    source: Literal["staff", "student", "computed", "none"]
    reasons: list[str]


class ClassifiedEntryOut(BaseModel):
    """One list entry with its classification."""

    entry_id: UUID
    institution_id: UUID
    classification: ClassificationOut


class BalanceOut(BaseModel):
    """Counts per label and a verdict code the web translates."""

    reach: int
    target: int
    safety: int
    unlabelled: int
    status: Literal["empty", "too_few", "no_safety", "too_many_reach", "balanced"]


class ListInsightsOut(BaseModel):
    """`profile_used` is false when the profile was not readable or empty."""

    entries: list[ClassifiedEntryOut]
    balance: BalanceOut
    profile_used: bool


class ListSuggestionOut(BaseModel):
    """An institution the model suggests adding, with a short reason."""

    institution_id: UUID
    name: str
    country: str
    label: Label
    reason: str


class ListSuggestionsOut(BaseModel):
    """The suggestions, at most six."""

    items: list[ListSuggestionOut]


async def list_insights(
    container: ContainerDep,
    ctx: AdmissionCtx,
    student_id: Annotated[UUID | None, Query()] = None,
) -> ListInsightsOut:
    """Classification and balance of my list or of a student's list."""
    res = await container.admission.list_plan.insights(ctx, student_id or ctx.user_id)
    return ListInsightsOut(
        entries=[
            ClassifiedEntryOut(
                entry_id=e.entry_id,
                institution_id=e.institution_id,
                classification=ClassificationOut(
                    computed=e.classification.computed,
                    effective=e.classification.effective,
                    source=e.classification.source,
                    reasons=list(e.classification.reasons),
                ),
            )
            for e in res.entries
        ],
        balance=BalanceOut(
            reach=res.balance.reach,
            target=res.balance.target,
            safety=res.balance.safety,
            unlabelled=res.balance.unlabelled,
            status=res.balance.status,
        ),
        profile_used=res.profile_used,
    )


async def suggest_list(
    container: ContainerDep, ctx: StudentCtx, accept_language: Lang = None
) -> ListSuggestionsOut:
    """AI ideas for my list (needs the `admission_ai` consent)."""
    rows = await container.admission.list_plan.suggest(ctx, _locale(accept_language))
    return ListSuggestionsOut(
        items=[
            ListSuggestionOut(
                institution_id=s.institution.id,
                name=s.institution.name,
                country=s.institution.country,
                label=s.label,
                reason=s.reason,
            )
            for s in rows
        ]
    )


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_route(
    "/list/insights",
    list_insights,
    "GET",
    "list_insights",
    response_model=ListInsightsOut,
)
_route(
    "/list/suggest",
    suggest_list,
    "POST",
    "suggest_list",
    response_model=ListSuggestionsOut,
)
