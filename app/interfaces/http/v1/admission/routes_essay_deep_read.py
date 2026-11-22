"""Deep read of an essay and the group critique over its target universities."""

from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep
from app.interfaces.http.v1.admission.routes_essay_reviews import EssayReviewsOut
from app.interfaces.http.v1.admission.routes_essays import Lang
from app.interfaces.http.v1.admission.routes_exemplars import ProblemOut
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.essay_deep_read import DeepReadResult

from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class DeepReadIn(BaseModel):
    """`refresh` ignores the stored reading and reads again."""

    refresh: bool = False


class GroupCritiqueIn(BaseModel):
    """`refresh` ignores stored reviews and reviews again.

    `institution_ids` limits the review to those targets (all when omitted).
    """

    refresh: bool = False
    institution_ids: list[UUID] | None = None


class ParagraphReadOut(BaseModel):
    """What one paragraph (1-based) does and reveals about the writer."""

    paragraph: int
    role: Literal["hook", "context", "turn", "evidence", "insight", "close"]
    reveals: str
    strength: Literal["strong", "ok", "weak"]


class MomentOut(BaseModel):
    """A line (verbatim from the essay) that lands an insight."""

    paragraph: int
    quote: str
    kind: Literal["surprising", "fresh", "earned"]


class DeepReadBodyOut(BaseModel):
    """The reading: paragraphs, uniqueness 0-100, tropes, moments and one fix."""

    paragraphs: list[ParagraphReadOut]
    uniqueness: int
    uniqueness_note: str
    tropes: list[str]
    moments: list[MomentOut]
    fix_paragraph: int
    fix_dimension: str
    fix_problem: str
    fix_try: str


class DeepReadOut(BaseModel):
    """The stored deep read (`read` is null before the first run)."""

    read: DeepReadBodyOut | None
    cached: bool
    stale: bool

    @classmethod
    def of(cls, r: DeepReadResult | None) -> "DeepReadOut":
        """Map the service result."""
        if r is None:
            return cls(read=None, cached=False, stale=False)
        d = r.read
        return cls(
            read=DeepReadBodyOut(
                paragraphs=[
                    ParagraphReadOut(
                        paragraph=p.paragraph,
                        role=p.role,
                        reveals=p.reveals,
                        strength=p.strength,
                    )
                    for p in d.paragraphs
                ],
                uniqueness=d.uniqueness,
                uniqueness_note=d.uniqueness_note,
                tropes=list(d.tropes),
                moments=[
                    MomentOut(
                        paragraph=m.paragraph,
                        quote=m.quote,
                        kind=m.kind,
                    )
                    for m in d.moments
                ],
                fix_paragraph=d.fix_paragraph,
                fix_dimension=d.fix_dimension,
                fix_problem=d.fix_problem,
                fix_try=d.fix_try,
            ),
            cached=r.cached,
            stale=r.stale,
        )


async def run_deep_read(
    essay_id: UUID,
    body: DeepReadIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    lang: Lang = None,
) -> DeepReadOut:
    """Read my essay paragraph by paragraph (AI consent, weekly review limit)."""
    r = await container.admission.essay_deep_read.run(
        ctx, essay_id, refresh=body.refresh, locale=_locale(lang)
    )
    return DeepReadOut.of(r)


async def get_deep_read(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx, lang: Lang = None
) -> DeepReadOut:
    """My stored deep read, marked stale when the essay changed; no model call."""
    r = await container.admission.essay_deep_read.get(ctx, essay_id, _locale(lang))
    return DeepReadOut.of(r)


async def group_critique(
    essay_id: UUID,
    body: GroupCritiqueIn,
    container: ContainerDep,
    ctx: AdmissionCtx,
    lang: Lang = None,
) -> EssayReviewsOut:
    """Review my essay for each target university under that target's prompt."""
    r = await container.admission.essay_deep_read.group_critique(
        ctx,
        essay_id,
        refresh=body.refresh,
        locale=_locale(lang),
        institution_ids=body.institution_ids,
    )
    return EssayReviewsOut.of(r)


class ReadHistoryItemOut(BaseModel):
    """One past deep read: when, how long the essay was, the gist, the unis."""

    id: UUID
    created_at: datetime
    words: int
    summary: str
    universities: list[UUID]


class StoredReadOut(BaseModel):
    """One past deep read, read-only; `latest` when no newer read exists."""

    id: UUID
    created_at: datetime
    latest: bool
    read: DeepReadBodyOut


async def get_deep_read_history(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> list[ReadHistoryItemOut]:
    """My past deep reads of this essay, newest first; no model call."""
    items = await container.admission.essay_deep_read.history(ctx, essay_id)
    return [
        ReadHistoryItemOut(
            id=i.id,
            created_at=i.created_at,
            words=i.words,
            summary=i.summary,
            universities=list(i.universities),
        )
        for i in items
    ]


async def get_stored_read(
    essay_id: UUID, read_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> StoredReadOut:
    """One past deep read of my essay."""
    s = await container.admission.essay_deep_read.stored_read(ctx, essay_id, read_id)
    body = DeepReadOut.of(DeepReadResult(s.read, True, False)).read
    assert body is not None
    return StoredReadOut(id=s.id, created_at=s.created_at, latest=s.latest, read=body)


def _route(path: str, endpoint: Any, method: str, op: str, model: Any) -> None:
    router.add_api_route(
        path,
        endpoint,
        methods=[method],
        operation_id=f"admission_essay_{op}",
        response_model=model,
        responses={
            403: {"model": ProblemOut, "description": "Not the owner, or no AI."},
            404: {"model": ProblemOut, "description": "Not my essay."},
            422: {"model": ProblemOut, "description": "The essay has under 50 words."},
            429: {"model": ProblemOut, "description": "The weekly limit is used up."},
        },
    )


_route("/essays/{essay_id}/deep-read", run_deep_read, "POST", "deep_read", DeepReadOut)
_route(
    "/essays/{essay_id}/deep-read", get_deep_read, "GET", "deep_read_get", DeepReadOut
)
_route(
    "/essays/{essay_id}/group-critique",
    group_critique,
    "POST",
    "group_critique",
    EssayReviewsOut,
)
_route(
    "/essays/{essay_id}/deep-read/history",
    get_deep_read_history,
    "GET",
    "deep_read_history",
    list[ReadHistoryItemOut],
)
_route(
    "/essays/{essay_id}/deep-read/{read_id}",
    get_stored_read,
    "GET",
    "deep_read_by_id",
    StoredReadOut,
)
