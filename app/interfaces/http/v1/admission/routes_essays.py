"""Essay workspace routes (`/v1/admission/essays*`, `/v1/admission/essay-ideas*`)."""

import datetime as dt
from typing import Annotated, Any, Literal
from uuid import UUID

from app.interfaces.http.v1.admission.deps import AdmissionCtx, ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_items import _locale
from app.modules.admission.application.essay_deep_read import ReadState
from app.modules.admission.application.essay_review_core import EssayCheck
from app.modules.admission.application.essays import SharedEssay
from app.modules.admission.domain.essay_flow import MAX_GROUP, PromptTarget
from app.modules.admission.domain.essays import (
    BODY_MAX,
    HEADING_MAX,
    IDEA_MAX,
    MAX_LINKS,
    MAX_SECTIONS,
    MAX_TAGS,
    NOTES_MAX,
    PROMPT_MAX,
    SECTION_NOTE_MAX,
    TAG_MAX,
    TITLE_MAX,
    VERSION_NAME_MAX,
    WORD_LIMIT_MAX,
    Essay,
    EssayIdea,
    EssayVersion,
)

from fastapi import APIRouter, Header, Response, status
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])

Lang = Annotated[str | None, Header(alias="Accept-Language")]
EssayKindT = Literal["personal_statement", "supplemental", "other"]
IdeaStatusT = Literal["explore", "keep", "drop"]


class PlanSectionIO(BaseModel):
    """One outline section of the plan."""

    heading: str = Field(min_length=1, max_length=HEADING_MAX)
    note: str = Field(default="", max_length=SECTION_NOTE_MAX)


class EssayLinkIO(BaseModel):
    """A link to an item id or a profile question id."""

    kind: Literal["item", "profile_answer"]
    ref: str = Field(min_length=1, max_length=64)


class PromptTargetIn(BaseModel):
    """A prompt the draft answers: `institution_id` null is the Common App."""

    institution_id: UUID | None = None
    position: int = Field(ge=0, le=999)


class PromptTargetOut(BaseModel):
    """A prompt the draft answers, with the text copied from the catalog."""

    institution_id: UUID | None
    position: int
    prompt: str
    word_limit: int | None


class EssayIn(BaseModel):
    """A new essay; supplemental essays need `list_entry_id`."""

    kind: EssayKindT = "personal_statement"
    title: str = Field(default="", max_length=TITLE_MAX)
    prompt_text: str = Field(default="", max_length=PROMPT_MAX)
    word_limit: int | None = Field(default=None, ge=1, le=WORD_LIMIT_MAX)
    list_entry_id: UUID | None = None
    targets: list[PromptTargetIn] = Field(default_factory=list, max_length=MAX_GROUP)


class EssayPatchIn(BaseModel):
    """Autosave: changed fields and the `lock_version` the client read."""

    lock_version: int = Field(ge=0)
    kind: EssayKindT | None = None
    title: str | None = Field(default=None, max_length=TITLE_MAX)
    prompt_text: str | None = Field(default=None, max_length=PROMPT_MAX)
    word_limit: int | None = Field(default=None, ge=1, le=WORD_LIMIT_MAX)
    list_entry_id: UUID | None = None
    body: str | None = Field(default=None, max_length=BODY_MAX)
    notes: str | None = Field(default=None, max_length=NOTES_MAX)
    plan: list[PlanSectionIO] | None = Field(default=None, max_length=MAX_SECTIONS)
    links: list[EssayLinkIO] | None = Field(default=None, max_length=MAX_LINKS)
    status: Literal["draft", "final"] | None = None
    targets: list[PromptTargetIn] | None = Field(default=None, max_length=MAX_GROUP)


class EssayOut(BaseModel):
    """The owner's essay with its live draft."""

    id: UUID
    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    list_entry_id: UUID | None
    body: str
    word_count: int
    notes: str
    plan: list[PlanSectionIO]
    links: list[EssayLinkIO]
    status: str
    current_version: int
    lock_version: int
    targets: list[PromptTargetOut]
    forked_from: UUID | None
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, e: Essay) -> "EssayOut":
        """Map the essay."""
        return cls(
            id=e.id,
            kind=e.kind,
            title=e.title,
            prompt_text=e.prompt_text,
            word_limit=e.word_limit,
            list_entry_id=e.list_entry_id,
            body=e.body,
            word_count=e.word_count,
            notes=e.notes,
            plan=[PlanSectionIO(heading=s.heading, note=s.note) for s in e.plan],
            links=[EssayLinkIO(kind=lk.kind, ref=lk.ref) for lk in e.links],
            status=e.status,
            current_version=e.current_version,
            lock_version=e.lock_version,
            targets=[
                PromptTargetOut(
                    institution_id=t.institution_id,
                    position=t.position,
                    prompt=t.prompt,
                    word_limit=t.word_limit,
                )
                for t in e.targets
            ],
            forked_from=e.forked_from,
            updated_at=e.updated_at,
        )


def _target_out(t: PromptTarget) -> PromptTargetOut:
    return PromptTargetOut(
        institution_id=t.institution_id,
        position=t.position,
        prompt=t.prompt,
        word_limit=t.word_limit,
    )


class EssaySummaryOut(BaseModel):
    """A row of the essays list."""

    id: UUID
    kind: str
    title: str
    word_limit: int | None
    list_entry_id: UUID | None
    word_count: int
    status: str
    updated_at: dt.datetime | None
    forked_from: UUID | None
    targets: list[PromptTargetOut]
    uniqueness: int | None = Field(
        description="The one score shown everywhere: deep-read uniqueness 0-100."
    )
    deep_read: Literal["none", "fresh", "stale"] = Field(
        description="`stale` when the essay (or the UI language) changed since."
    )
    deep_read_at: dt.datetime | None
    unreadable: bool = Field(
        default=False,
        description="The sealed text is lost (key gone or changed): no text, "
        "only deletion is possible.",
    )

    @classmethod
    def of(cls, e: Essay, read: ReadState | None = None) -> "EssaySummaryOut":
        """Map the essay without its texts, with its stored deep read state."""
        return cls(
            id=e.id,
            kind=e.kind,
            title=e.title,
            word_limit=e.word_limit,
            list_entry_id=e.list_entry_id,
            word_count=e.word_count,
            status=e.status,
            updated_at=e.updated_at,
            forked_from=e.forked_from,
            targets=[_target_out(t) for t in e.targets],
            uniqueness=None if read is None else read.uniqueness,
            deep_read="none" if read is None else read.state,
            deep_read_at=None if read is None else read.read_at,
            unreadable=e.unreadable,
        )


class EssayListOut(BaseModel):
    """The owner's essays."""

    items: list[EssaySummaryOut]


class SnapshotIn(BaseModel):
    """Save a version now; `name` is optional."""

    lock_version: int = Field(ge=0)
    name: str | None = Field(default=None, max_length=VERSION_NAME_MAX)


class RestoreIn(BaseModel):
    """The `lock_version` of the essay the client read."""

    lock_version: int = Field(ge=0)


class ShareIn(BaseModel):
    """Whether staff in scope may read this version."""

    shared: bool


class EssayVersionOut(BaseModel):
    """One snapshot of the draft."""

    version: int
    body: str
    word_count: int
    source: str
    name: str | None
    shared: bool
    created_at: dt.datetime | None

    @classmethod
    def of(cls, v: EssayVersion) -> "EssayVersionOut":
        """Map the version."""
        return cls(
            version=v.version,
            body=v.body,
            word_count=v.word_count,
            source=v.source,
            name=v.name,
            shared=v.shared,
            created_at=v.created_at,
        )


class EssayVersionListOut(BaseModel):
    """Versions, newest first."""

    items: list[EssayVersionOut]


class SharedEssayOut(BaseModel):
    """An essay as staff see it: the brief and the shared versions only."""

    id: UUID
    student_id: UUID
    kind: str
    title: str
    prompt_text: str
    word_limit: int | None
    list_entry_id: UUID | None
    versions: list[EssayVersionOut]

    @classmethod
    def of(cls, s: SharedEssay) -> "SharedEssayOut":
        """Map the shared view."""
        e = s.essay
        return cls(
            id=e.id,
            student_id=e.student_id,
            kind=e.kind,
            title=e.title,
            prompt_text=e.prompt_text,
            word_limit=e.word_limit,
            list_entry_id=e.list_entry_id,
            versions=[EssayVersionOut.of(v) for v in s.versions],
        )


class SharedEssayListOut(BaseModel):
    """A student's essays with shared versions."""

    items: list[SharedEssayOut]


class IdeaIn(BaseModel):
    """A new idea card."""

    body: str = Field(min_length=1, max_length=IDEA_MAX)
    essay_id: UUID | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=TAG_MAX)]] = Field(
        default_factory=list, max_length=MAX_TAGS
    )
    status: IdeaStatusT = "explore"
    sort_order: int = Field(default=0, ge=0, le=1000)


class IdeaPatchIn(BaseModel):
    """Changed fields of an idea; `essay_id: null` unlinks it."""

    lock_version: int = Field(ge=0)
    body: str | None = Field(default=None, min_length=1, max_length=IDEA_MAX)
    essay_id: UUID | None = None
    tags: list[Annotated[str, Field(min_length=1, max_length=TAG_MAX)]] | None = Field(
        default=None, max_length=MAX_TAGS
    )
    status: IdeaStatusT | None = None
    sort_order: int | None = Field(default=None, ge=0, le=1000)


class IdeaOut(BaseModel):
    """An idea card."""

    id: UUID
    body: str
    essay_id: UUID | None
    tags: list[str]
    status: str
    sort_order: int
    lock_version: int
    updated_at: dt.datetime | None

    @classmethod
    def of(cls, i: EssayIdea) -> "IdeaOut":
        """Map the idea."""
        return cls(
            id=i.id,
            body=i.body,
            essay_id=i.essay_id,
            tags=list(i.tags),
            status=i.status,
            sort_order=i.sort_order,
            lock_version=i.lock_version,
            updated_at=i.updated_at,
        )


class IdeaListOut(BaseModel):
    """The ideas board."""

    items: list[IdeaOut]


class CoachQuestionsOut(BaseModel):
    """Questions to think about; the coach never writes the essay."""

    questions: list[str]


class CoachExpansionOut(BaseModel):
    """How the idea could fit and angles to explore."""

    fit: str
    angles: list[str]


class CoachSectionOut(BaseModel):
    """A proposed outline section; add it to the plan yourself."""

    heading: str
    note: str
    share_percent: int


class CoachOutlineOut(BaseModel):
    """Proposed outline sections."""

    sections: list[CoachSectionOut]


class CoachSentenceOut(BaseModel):
    """A comment on one sentence."""

    quote: str
    comment: str


class CoachReviewIn(BaseModel):
    """How to review the draft; `excerpt` is used by `partial`."""

    mode: Literal["overall", "sentences", "both", "partial"] = "overall"
    excerpt: str = Field(default="", max_length=BODY_MAX)


class CoachRefineIn(BaseModel):
    """A passage to polish."""

    action: Literal["reword", "transition", "merge"]
    text: str = Field(min_length=1, max_length=2000)


class CoachHintsOut(BaseModel):
    """Hints for polishing a passage."""

    hints: list[str]


class LifeStoryIn(BaseModel):
    """A free life story."""

    text: str = Field(min_length=1, max_length=BODY_MAX)


class LifeStoryOut(BaseModel):
    """What the story shows."""

    drivers: list[str]
    support: list[str]
    leave_out: list[str]
    ideas: list[str]


class CoachFeedbackOut(BaseModel):
    """Comments on the draft against its prompt and word limit."""

    sentences: list[CoachSentenceOut] = []
    summary: str
    strengths: list[str]
    suggestions: list[str]
    word_count: int
    word_limit: int | None


CheckDimT = Literal["hook", "theme", "detail", "authenticity", "reflection", "writing"]


class CoachCheckDimensionOut(BaseModel):
    """One rubric dimension: score 0-5, a verified quote and a comment."""

    dim: CheckDimT
    score: int
    quote: str | None
    comment: str


class CoachCheckOut(BaseModel):
    """The draft scored on six dimensions against its prompt; the latest is stored."""

    score: int
    band: Literal["exceptional", "strong", "solid", "developing", "weak"]
    dimensions: list[CoachCheckDimensionOut]
    prompt_fit: Literal["yes", "partial", "no", "unknown"]
    prompt_fit_reason: str
    strongest: CheckDimT
    first_fix: str
    flagged_paragraph: int | None
    flagged_text: str | None
    flagged_reason: str
    summary: str
    word_count: int
    word_limit: int | None
    over_limit: bool
    generic: bool


class LatestCheckOut(CoachCheckOut):
    """The stored latest check; `stale` when the draft changed since."""

    stale: bool
    created_at: dt.datetime


async def list_essays(
    container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> EssayListOut:
    """My essays with forks, targets and the stored deep-read score (no model call)."""
    rows = await container.admission.essays.mine(ctx)
    states = await container.admission.essay_deep_read.states(ctx, rows, _locale(lang))
    return EssayListOut(items=[EssaySummaryOut.of(e, states.get(e.id)) for e in rows])


async def create_essay(
    body: EssayIn, container: ContainerDep, ctx: StudentCtx
) -> EssayOut:
    """Start an essay (at most 40)."""
    return EssayOut.of(await container.admission.essays.create(ctx, body.model_dump()))


async def get_essay(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> EssayOut:
    """One of my essays with its draft, notes and plan."""
    return EssayOut.of(await container.admission.essays.get(ctx, essay_id))


async def patch_essay(
    essay_id: UUID, body: EssayPatchIn, container: ContainerDep, ctx: StudentCtx
) -> EssayOut:
    """Autosave; 409 when another tab saved first. May snapshot a version."""
    changes = body.model_dump(exclude_unset=True, exclude={"lock_version"})
    for key in (
        "kind",
        "title",
        "prompt_text",
        "body",
        "notes",
        "plan",
        "links",
        "targets",
    ):
        if key in changes and changes[key] is None:
            del changes[key]
    if changes.get("status") is None:
        changes.pop("status", None)
    stored = await container.admission.essays.save(
        ctx, essay_id, body.lock_version, changes
    )
    return EssayOut.of(stored)


async def delete_essay(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> Response:
    """Delete my essay and its versions."""
    await container.admission.essays.delete(ctx, essay_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def list_versions(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> EssayVersionListOut:
    """All versions of my essay, newest first."""
    rows = await container.admission.essays.versions(ctx, essay_id)
    return EssayVersionListOut(items=[EssayVersionOut.of(v) for v in rows])


async def snapshot_essay(
    essay_id: UUID, body: SnapshotIn, container: ContainerDep, ctx: StudentCtx
) -> EssayVersionOut:
    """Save the current draft as a version."""
    out = await container.admission.essays.snapshot(
        ctx, essay_id, body.lock_version, body.name
    )
    return EssayVersionOut.of(out)


async def restore_version(
    essay_id: UUID,
    version: int,
    body: RestoreIn,
    container: ContainerDep,
    ctx: StudentCtx,
) -> EssayOut:
    """Restore an old version; the current draft is kept as a version first."""
    out = await container.admission.essays.restore(
        ctx, essay_id, version, body.lock_version
    )
    return EssayOut.of(out)


async def share_version(
    essay_id: UUID,
    version: int,
    body: ShareIn,
    container: ContainerDep,
    ctx: StudentCtx,
) -> EssayVersionOut:
    """Share or unshare a version with my mentors and counselors."""
    out = await container.admission.essays.share(ctx, essay_id, version, body.shared)
    return EssayVersionOut.of(out)


async def get_shared_essay(
    essay_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> SharedEssayOut:
    """An essay's shared versions (staff in scope)."""
    return SharedEssayOut.of(
        await container.admission.essays.shared_view(ctx, essay_id)
    )


async def list_student_essays(
    student_id: UUID, container: ContainerDep, ctx: AdmissionCtx
) -> SharedEssayListOut:
    """A student's essays with shared versions (staff in scope)."""
    rows = await container.admission.essays.list_shared(ctx, student_id)
    return SharedEssayListOut(items=[SharedEssayOut.of(s) for s in rows])


async def list_ideas(container: ContainerDep, ctx: StudentCtx) -> IdeaListOut:
    """My ideas board."""
    rows = await container.admission.essays.ideas(ctx)
    return IdeaListOut(items=[IdeaOut.of(i) for i in rows])


async def create_idea(
    body: IdeaIn, container: ContainerDep, ctx: StudentCtx
) -> IdeaOut:
    """Pin an idea (at most 100)."""
    return IdeaOut.of(await container.admission.essays.add_idea(ctx, body.model_dump()))


async def patch_idea(
    idea_id: UUID, body: IdeaPatchIn, container: ContainerDep, ctx: StudentCtx
) -> IdeaOut:
    """Change an idea."""
    changes = body.model_dump(exclude_unset=True, exclude={"lock_version"})
    for key in ("body", "tags", "status", "sort_order"):
        if key in changes and changes[key] is None:
            del changes[key]
    out = await container.admission.essays.update_idea(
        ctx, idea_id, body.lock_version, changes
    )
    return IdeaOut.of(out)


async def delete_idea(
    idea_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> Response:
    """Delete an idea."""
    await container.admission.essays.delete_idea(ctx, idea_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


async def coach_brainstorm(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> CoachQuestionsOut:
    """Questions that help me find my story (AI consent and a daily limit apply)."""
    out = await container.admission.essay_coach.brainstorm(ctx, essay_id, _locale(lang))
    return CoachQuestionsOut(questions=out)


async def coach_outline(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> CoachOutlineOut:
    """A proposed outline (AI consent and a daily limit apply)."""
    out = await container.admission.essay_coach.outline(ctx, essay_id, _locale(lang))
    return CoachOutlineOut(
        sections=[
            CoachSectionOut(
                heading=s.heading, note=s.note, share_percent=s.share_percent
            )
            for s in out
        ]
    )


async def coach_feedback(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> CoachFeedbackOut:
    """Feedback on my draft (AI consent and a daily limit apply)."""
    f = await container.admission.essay_coach.feedback(ctx, essay_id, _locale(lang))
    return CoachFeedbackOut(
        summary=f.summary,
        strengths=f.strengths,
        suggestions=f.suggestions,
        word_count=f.word_count,
        word_limit=f.word_limit,
    )


async def coach_check(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> CoachCheckOut:
    """Score my draft on six dimensions against its prompt (AI consent, daily limit)."""
    c = await container.admission.essay_coach.check(ctx, essay_id, _locale(lang))
    return CoachCheckOut(**_check_fields(c))


async def latest_check(
    essay_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> LatestCheckOut:
    """My latest stored check; 404 before the first check, no model call."""
    c, stale, at = await container.admission.essay_coach.latest_check(
        ctx, essay_id, _locale(lang)
    )
    return LatestCheckOut(**_check_fields(c), stale=stale, created_at=at)


def _check_fields(c: EssayCheck) -> dict[str, Any]:
    return {
        "score": c.score,
        "band": c.band,
        "dimensions": [
            CoachCheckDimensionOut(
                dim=d.dim, score=d.score, quote=d.quote, comment=d.comment
            )
            for d in c.dimensions
        ],
        "prompt_fit": c.prompt_fit,
        "prompt_fit_reason": c.prompt_fit_reason,
        "strongest": c.strongest,
        "first_fix": c.first_fix,
        "flagged_paragraph": c.flagged_paragraph,
        "flagged_text": c.flagged_text,
        "flagged_reason": c.flagged_reason,
        "summary": c.summary,
        "word_count": c.word_count,
        "word_limit": c.word_limit,
        "over_limit": c.over_limit,
        "generic": c.generic,
    }


async def coach_review(
    essay_id: UUID,
    body: CoachReviewIn,
    container: ContainerDep,
    ctx: StudentCtx,
    lang: Lang = None,
) -> CoachFeedbackOut:
    """Review my draft overall, by sentence, both or one excerpt (AI consent)."""
    f = await container.admission.essay_coach.review(
        ctx, essay_id, _locale(lang), body.mode, body.excerpt
    )
    return CoachFeedbackOut(
        summary=f.summary,
        strengths=f.strengths,
        suggestions=f.suggestions,
        word_count=f.word_count,
        word_limit=f.word_limit,
        sentences=[
            CoachSentenceOut(quote=n.quote, comment=n.comment) for n in f.sentences
        ],
    )


async def coach_refine(
    essay_id: UUID,
    body: CoachRefineIn,
    container: ContainerDep,
    ctx: StudentCtx,
    lang: Lang = None,
) -> CoachHintsOut:
    """Hints to reword, connect or merge a passage; never new text (AI consent)."""
    out = await container.admission.essay_coach.refine(
        ctx, essay_id, _locale(lang), body.action, body.text
    )
    return CoachHintsOut(hints=out)


async def read_life_story(
    body: LifeStoryIn, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> LifeStoryOut:
    """What drives me, what to support and leave out (AI consent)."""
    r = await container.admission.essay_coach.life_story(ctx, body.text, _locale(lang))
    return LifeStoryOut(
        drivers=r.drivers, support=r.support, leave_out=r.leave_out, ideas=r.ideas
    )


async def coach_expand(
    idea_id: UUID, container: ContainerDep, ctx: StudentCtx, lang: Lang = None
) -> CoachExpansionOut:
    """Angles on one idea (AI consent and a daily limit apply)."""
    out = await container.admission.essay_coach.expand(ctx, idea_id, _locale(lang))
    return CoachExpansionOut(fit=out.fit, angles=out.angles)


def _route(path: str, endpoint: Any, method: str, op: str, **kw: Any) -> None:
    router.add_api_route(
        path, endpoint, methods=[method], operation_id=f"admission_{op}", **kw
    )


_CREATED = {"status_code": status.HTTP_201_CREATED}
_GONE = {"status_code": status.HTTP_204_NO_CONTENT}

_route("/essays", list_essays, "GET", "list_essays", response_model=EssayListOut)
_route(
    "/essays", create_essay, "POST", "create_essay", response_model=EssayOut, **_CREATED
)
_route("/essays/{essay_id}", get_essay, "GET", "get_essay", response_model=EssayOut)
_route(
    "/essays/{essay_id}", patch_essay, "PATCH", "patch_essay", response_model=EssayOut
)
_route("/essays/{essay_id}", delete_essay, "DELETE", "delete_essay", **_GONE)
_route(
    "/essays/{essay_id}/versions",
    list_versions,
    "GET",
    "list_essay_versions",
    response_model=EssayVersionListOut,
)
_route(
    "/essays/{essay_id}/versions",
    snapshot_essay,
    "POST",
    "snapshot_essay",
    response_model=EssayVersionOut,
    **_CREATED,
)
_route(
    "/essays/{essay_id}/versions/{version}/restore",
    restore_version,
    "POST",
    "restore_essay_version",
    response_model=EssayOut,
)
_route(
    "/essays/{essay_id}/versions/{version}/share",
    share_version,
    "PUT",
    "share_essay_version",
    response_model=EssayVersionOut,
)
_route(
    "/essays/{essay_id}/shared",
    get_shared_essay,
    "GET",
    "get_shared_essay",
    response_model=SharedEssayOut,
)
_route(
    "/students/{student_id}/essays",
    list_student_essays,
    "GET",
    "list_student_essays",
    response_model=SharedEssayListOut,
)
_route(
    "/essays/{essay_id}/coach/brainstorm",
    coach_brainstorm,
    "POST",
    "coach_essay_brainstorm",
    response_model=CoachQuestionsOut,
)
_route(
    "/essays/{essay_id}/coach/outline",
    coach_outline,
    "POST",
    "coach_essay_outline",
    response_model=CoachOutlineOut,
)
_route(
    "/essays/{essay_id}/coach/feedback",
    coach_feedback,
    "POST",
    "coach_essay_feedback",
    response_model=CoachFeedbackOut,
)
_route(
    "/essays/{essay_id}/coach/check",
    coach_check,
    "POST",
    "check_essay",
    response_model=CoachCheckOut,
)
_route(
    "/essays/{essay_id}/coach/check/latest",
    latest_check,
    "GET",
    "get_latest_essay_check",
    response_model=LatestCheckOut,
    responses={
        404: {"description": "Not my essay, or it has never been checked."},
        503: {"description": "The essay key service is down."},
    },
)
_route(
    "/essays/{essay_id}/coach/review",
    coach_review,
    "POST",
    "coach_essay_review",
    response_model=CoachFeedbackOut,
)
_route(
    "/essays/{essay_id}/coach/refine",
    coach_refine,
    "POST",
    "coach_essay_refine",
    response_model=CoachHintsOut,
)
_route(
    "/essay-life-story",
    read_life_story,
    "POST",
    "read_essay_life_story",
    response_model=LifeStoryOut,
)
_route(
    "/essay-ideas", list_ideas, "GET", "list_essay_ideas", response_model=IdeaListOut
)
_route(
    "/essay-ideas",
    create_idea,
    "POST",
    "create_essay_idea",
    response_model=IdeaOut,
    **_CREATED,
)
_route(
    "/essay-ideas/{idea_id}",
    patch_idea,
    "PATCH",
    "patch_essay_idea",
    response_model=IdeaOut,
)
_route("/essay-ideas/{idea_id}", delete_idea, "DELETE", "delete_essay_idea", **_GONE)
_route(
    "/essay-ideas/{idea_id}/expand",
    coach_expand,
    "POST",
    "coach_essay_idea_expand",
    response_model=CoachExpansionOut,
)
