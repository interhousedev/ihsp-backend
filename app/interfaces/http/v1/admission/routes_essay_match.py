"""Top essays and the per-university matching table (`/v1/admission/essays/...`)."""

import datetime as dt
from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.interfaces.http.v1.admission.routes_essay_prompt_map import ShortAnswerOut
from app.modules.admission.application.essay_match import (
    AssignedEssay,
    MatchCandidate,
    MatchSlot,
    MatchTable,
    TopEssay,
)

from fastapi import APIRouter
from pydantic import BaseModel, Field

router = APIRouter(prefix="/v1/admission", tags=["admission"])


class TopEssayOut(BaseModel):
    """An essay with its stored base review score, 0 to 100."""

    essay_id: str
    title: str
    kind: str
    word_count: int
    score: int
    band: str

    @classmethod
    def of(cls, t: TopEssay) -> "TopEssayOut":
        """Build from the service result."""
        return cls(
            essay_id=str(t.essay_id),
            title=t.title,
            kind=t.kind,
            word_count=t.word_count,
            score=t.score,
            band=t.band,
        )


class TopEssaysOut(BaseModel):
    """My best essays, at most ten, best first."""

    items: list[TopEssayOut]


class MatchCandidateOut(BaseModel):
    """An essay that may fill the slot; `alignment` is the stored review, 0-100."""

    essay_id: str
    title: str
    kind: str
    word_count: int
    alignment: int | None
    target_match: bool

    @classmethod
    def of(cls, c: MatchCandidate) -> "MatchCandidateOut":
        """Build from a candidate."""
        return cls(
            essay_id=str(c.essay_id),
            title=c.title,
            kind=c.kind,
            word_count=c.word_count,
            alignment=c.alignment,
            target_match=c.target_match,
        )


class AssignedEssayOut(BaseModel):
    """The essay placed in a slot, as it is now; `over_limit` against the slot."""

    essay_id: str
    title: str
    kind: str
    word_count: int
    status: str
    over_limit: bool

    @classmethod
    def of(cls, a: AssignedEssay) -> "AssignedEssayOut":
        """Build from the assigned essay."""
        return cls(
            essay_id=str(a.essay_id),
            title=a.title,
            kind=a.kind,
            word_count=a.word_count,
            status=a.status,
            over_limit=a.over_limit,
        )


class MatchSlotOut(BaseModel):
    """One slot: `ps` (no prompt) or `supp:<position>`; candidates best first."""

    slot: str
    prompt: str | None
    word_limit: int | None
    required: bool
    essay_id: str | None
    assigned: AssignedEssayOut | None
    candidates: list[MatchCandidateOut]
    shared: bool = Field(
        description="The personal statement of a Common App university: set once "
        "for all of them with `PUT /essays/match/common-app`."
    )
    category: str | None = Field(
        description="Prompt category (see the prompt map); null for no prompt."
    )
    prompt_key: str | None = Field(description="Key of the prompt; null for `ps`.")
    short_answer: ShortAnswerOut | None = Field(
        description="My short text; only on `short_answer` slots, null until written."
    )

    @classmethod
    def of(cls, s: MatchSlot) -> "MatchSlotOut":
        """Build from a slot."""
        return cls(
            slot=s.slot,
            prompt=s.prompt,
            word_limit=s.word_limit,
            required=s.required,
            assigned=None if s.assigned is None else AssignedEssayOut.of(s.assigned),
            essay_id=None if s.essay_id is None else str(s.essay_id),
            candidates=[MatchCandidateOut.of(c) for c in s.candidates],
            shared=s.shared,
            category=s.category,
            prompt_key=s.prompt_key,
            short_answer=(
                None if s.short_answer is None else ShortAnswerOut.of(s.short_answer)
            ),
        )


class MatchTableOut(BaseModel):
    """The matching table of one university."""

    institution_id: str
    institution_name: str
    due_utc: dt.datetime | None
    due_predicted: bool
    slots: list[MatchSlotOut]

    @classmethod
    def of(cls, t: MatchTable) -> "MatchTableOut":
        """Build from the table."""
        return cls(
            institution_id=str(t.institution_id),
            institution_name=t.institution_name,
            due_utc=t.due_utc,
            due_predicted=t.due_predicted,
            slots=[MatchSlotOut.of(s) for s in t.slots],
        )


class EssayMatchListOut(BaseModel):
    """The tables of every university on my list, soonest due first."""

    items: list[MatchTableOut]


class SlotIn(BaseModel):
    """The essay to place into the slot."""

    essay_id: UUID


class CommonAppIn(BaseModel):
    """The personal statement for every Common App university; null empties it."""

    essay_id: UUID | None


class ShortAnswerIn(BaseModel):
    """The short text (at most 150 words and the prompt's own limit)."""

    text: str = Field(max_length=2000)


@router.get(
    "/essays/top", operation_id="admission_essay_top", response_model=TopEssaysOut
)
async def essay_top(container: ContainerDep, ctx: StudentCtx) -> TopEssaysOut:
    """My best essays by stored review score (at most ten)."""
    rows = await container.admission.essay_match.top(ctx)
    return TopEssaysOut(items=[TopEssayOut.of(t) for t in rows])


@router.get(
    "/essays/match",
    operation_id="admission_essay_match_list",
    response_model=EssayMatchListOut,
)
async def essay_match_list(
    container: ContainerDep, ctx: StudentCtx
) -> EssayMatchListOut:
    """Every listed university's slots at once, with its application due date."""
    tables = await container.admission.essay_match.listing(ctx)
    return EssayMatchListOut(items=[MatchTableOut.of(t) for t in tables])


@router.get(
    "/essays/match/{university_id}",
    operation_id="admission_essay_match",
    response_model=MatchTableOut,
)
async def essay_match(
    university_id: UUID, container: ContainerDep, ctx: StudentCtx
) -> MatchTableOut:
    """The slots of a university with the essays that may fill them."""
    table = await container.admission.essay_match.table(ctx, university_id)
    return MatchTableOut.of(table)


@router.put(
    "/essays/match/{university_id}/slots/{slot_key}",
    operation_id="admission_essay_match_assign",
    response_model=MatchTableOut,
)
async def essay_match_assign(
    university_id: UUID,
    slot_key: str,
    body: SlotIn,
    container: ContainerDep,
    ctx: StudentCtx,
) -> MatchTableOut:
    """Place an essay into a slot; it leaves its other slot of the university."""
    table = await container.admission.essay_match.assign(
        ctx, university_id, slot_key, body.essay_id
    )
    return MatchTableOut.of(table)


@router.delete(
    "/essays/match/{university_id}/slots/{slot_key}",
    operation_id="admission_essay_match_clear",
    response_model=MatchTableOut,
)
async def essay_match_clear(
    university_id: UUID, slot_key: str, container: ContainerDep, ctx: StudentCtx
) -> MatchTableOut:
    """Empty a slot."""
    table = await container.admission.essay_match.clear(ctx, university_id, slot_key)
    return MatchTableOut.of(table)


@router.put(
    "/essays/match/common-app",
    operation_id="admission_essay_match_common_app",
    response_model=EssayMatchListOut,
)
async def essay_match_common_app(
    body: CommonAppIn, container: ContainerDep, ctx: StudentCtx
) -> EssayMatchListOut:
    """Fill or empty the shared personal statement of every Common App university."""
    tables = await container.admission.essay_match.set_common_app(ctx, body.essay_id)
    return EssayMatchListOut(items=[MatchTableOut.of(t) for t in tables])


@router.get(
    "/essays/short-answers/{slot_key}",
    operation_id="admission_essay_short_answer",
    response_model=ShortAnswerOut,
)
async def essay_short_answer(
    slot_key: str, container: ContainerDep, ctx: StudentCtx
) -> ShortAnswerOut:
    """My short answer to a supplemental prompt (`slot_key` is the prompt key)."""
    got = await container.admission.essay_short_answers.get(ctx, slot_key)
    return ShortAnswerOut.of(got)


@router.put(
    "/essays/short-answers/{slot_key}",
    operation_id="admission_essay_short_answer_put",
    response_model=ShortAnswerOut,
)
async def essay_short_answer_put(
    slot_key: str, body: ShortAnswerIn, container: ContainerDep, ctx: StudentCtx
) -> ShortAnswerOut:
    """Store the short answer sealed; 422 above 150 words or the prompt's limit."""
    saved = await container.admission.essay_short_answers.put(ctx, slot_key, body.text)
    return ShortAnswerOut.of(saved)
