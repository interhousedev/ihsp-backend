"""Top essays and the per-university matching table (`/v1/admission/essays/...`)."""

from uuid import UUID

from app.interfaces.http.v1.admission.deps import ContainerDep, StudentCtx
from app.modules.admission.application.essay_match import (
    MatchCandidate,
    MatchSlot,
    MatchTable,
    TopEssay,
)

from fastapi import APIRouter
from pydantic import BaseModel

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


class MatchSlotOut(BaseModel):
    """One slot: `ps` (no prompt) or `supp:<position>`; candidates best first."""

    slot: str
    prompt: str | None
    word_limit: int | None
    essay_id: str | None
    candidates: list[MatchCandidateOut]

    @classmethod
    def of(cls, s: MatchSlot) -> "MatchSlotOut":
        """Build from a slot."""
        return cls(
            slot=s.slot,
            prompt=s.prompt,
            word_limit=s.word_limit,
            essay_id=None if s.essay_id is None else str(s.essay_id),
            candidates=[MatchCandidateOut.of(c) for c in s.candidates],
        )


class MatchTableOut(BaseModel):
    """The matching table of one university."""

    institution_id: str
    institution_name: str
    slots: list[MatchSlotOut]

    @classmethod
    def of(cls, t: MatchTable) -> "MatchTableOut":
        """Build from the table."""
        return cls(
            institution_id=str(t.institution_id),
            institution_name=t.institution_name,
            slots=[MatchSlotOut.of(s) for s in t.slots],
        )


class SlotIn(BaseModel):
    """The essay to place into the slot."""

    essay_id: UUID


@router.get(
    "/essays/top", operation_id="admission_essay_top", response_model=TopEssaysOut
)
async def essay_top(container: ContainerDep, ctx: StudentCtx) -> TopEssaysOut:
    """My best essays by stored review score (at most ten)."""
    rows = await container.admission.essay_match.top(ctx)
    return TopEssaysOut(items=[TopEssayOut.of(t) for t in rows])


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
