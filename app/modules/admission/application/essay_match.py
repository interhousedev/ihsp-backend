"""Top essays and the per-university matching table.

Both read the stored reviews only (no model call). The table has one slot per
prompt of the university (`supp:<n>`) and the personal statement slot (`ps`),
which only personal statements may fill. An essay holds one slot per university.
"""

import datetime as dt
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.essay_due import DueDate, application_dues
from app.modules.admission.application.essay_prompts import FlowGate
from app.modules.admission.domain.errors import AdmissionNotFoundError
from app.modules.admission.domain.essay_flow import (
    PS_SLOT,
    TOP_ESSAYS,
    PromptRef,
    SlotAssignment,
    supp_slot,
    valid_slot,
)
from app.modules.admission.domain.essays import Essay
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.base_error import ValidationFailedError


@dataclass(frozen=True, slots=True)
class TopEssay:
    """An essay with its stored base review score (0 to 100)."""

    essay_id: UUID
    title: str
    kind: str
    word_count: int
    score: int
    band: str


@dataclass(frozen=True, slots=True)
class MatchCandidate:
    """An essay that may fill a slot, with what the stored reviews say of it."""

    essay_id: UUID
    title: str
    kind: str
    word_count: int
    alignment: int | None
    target_match: bool


@dataclass(frozen=True, slots=True)
class AssignedEssay:
    """The essay placed in a slot, as it is now."""

    essay_id: UUID
    title: str
    kind: str
    word_count: int
    status: str
    over_limit: bool


@dataclass(frozen=True, slots=True)
class MatchSlot:
    """One slot of the table: the prompt, the placed essay and the candidates."""

    slot: str
    prompt: str | None
    word_limit: int | None
    essay_id: UUID | None
    candidates: tuple[MatchCandidate, ...]
    required: bool = True
    assigned: AssignedEssay | None = None


@dataclass(frozen=True, slots=True)
class MatchTable:
    """The matching table of one university."""

    institution_id: UUID
    institution_name: str
    slots: tuple[MatchSlot, ...]
    due_utc: dt.datetime | None = None
    due_predicted: bool = False


def _held(essays: dict[UUID, Essay], essay_id: UUID | None) -> Essay | None:
    return None if essay_id is None else essays.get(essay_id)


def _assigned(essay: Essay | None, limit: int | None) -> AssignedEssay | None:
    if essay is None:
        return None
    return AssignedEssay(
        essay.id,
        essay.title,
        essay.kind,
        essay.word_count,
        essay.status,
        limit is not None and essay.word_count > limit,
    )


def _bad_slot() -> ValidationFailedError:
    return ValidationFailedError(params={"field": "slot"})


class EssayMatchService:
    """Best essays and which essay answers which prompt of a university."""

    def __init__(self, uow_factory: UowFactory, gate: FlowGate) -> None:
        """Keep the unit of work factory and the owner gate."""
        self._uow = uow_factory
        self._gate = gate

    async def top(self, ctx: AdmissionContext) -> list[TopEssay]:
        """My best essays by stored base review score, at most ten."""
        await self._gate.owner(ctx)
        out: list[TopEssay] = []
        async with self._uow() as uow:
            for essay in await uow.essays.list_for(ctx.user_id):
                base = next(
                    (
                        r
                        for r in await uow.essay_reviews.list_for_essay(essay.id)
                        if r.kind == "base"
                    ),
                    None,
                )
                if base is None:
                    continue
                out.append(
                    TopEssay(
                        essay.id,
                        essay.title,
                        essay.kind,
                        essay.word_count,
                        int(base.payload.get("score", 0)),
                        str(base.payload.get("band", "")),
                    )
                )
        out.sort(key=lambda t: (-t.score, -t.word_count))
        return out[:TOP_ESSAYS]

    async def table(self, ctx: AdmissionContext, institution_id: UUID) -> MatchTable:
        """The matching table of one university."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            return await self._table(uow, ctx.user_id, institution_id)

    async def listing(self, ctx: AdmissionContext) -> list[MatchTable]:
        """The tables of every university on my list, soonest due first."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            dues = await application_dues(uow, ctx.user_id)
            ids = list(
                dict.fromkeys(
                    e.institution_id for e in await uow.shortlist.entries(ctx.user_id)
                )
            )
            tables = [await self._table(uow, ctx.user_id, i, dues) for i in ids]
        far = dt.datetime.max.replace(tzinfo=dt.UTC)
        return sorted(tables, key=lambda t: (t.due_utc or far, t.institution_name))

    async def assign(
        self,
        ctx: AdmissionContext,
        institution_id: UUID,
        slot: str,
        essay_id: UUID,
    ) -> MatchTable:
        """Place an essay into a slot; it leaves its other slot of the university."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            _, refs = await self._university(uow, institution_id)
            if not valid_slot(slot) or slot not in {PS_SLOT, *(r.slot for r in refs)}:
                raise _bad_slot()
            essay = await uow.essays.get(essay_id)
            if essay is None or essay.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            if slot == PS_SLOT and essay.kind != "personal_statement":
                raise _bad_slot()
            await uow.slots.put(
                SlotAssignment(ctx.user_id, institution_id, slot, essay.id)
            )
            table = await self._table(uow, ctx.user_id, institution_id)
            await uow.commit()
        return table

    async def clear(
        self, ctx: AdmissionContext, institution_id: UUID, slot: str
    ) -> MatchTable:
        """Empty a slot (no error when it is already empty)."""
        await self._gate.owner(ctx)
        async with self._uow() as uow:
            _, refs = await self._university(uow, institution_id)
            if not valid_slot(slot) or slot not in {PS_SLOT, *(r.slot for r in refs)}:
                raise _bad_slot()
            await uow.slots.clear(ctx.user_id, institution_id, slot)
            table = await self._table(uow, ctx.user_id, institution_id)
            await uow.commit()
        return table

    @staticmethod
    async def _university(
        uow: AdmissionUnitOfWork, institution_id: UUID
    ) -> tuple[str, list[PromptRef]]:
        inst = await uow.catalog.institution(institution_id)
        if inst is None:
            raise AdmissionNotFoundError()
        return inst.name, await uow.prompt_catalog.for_institution(institution_id)

    async def _table(
        self,
        uow: AdmissionUnitOfWork,
        student_id: UUID,
        institution_id: UUID,
        dues: dict[UUID, DueDate] | None = None,
    ) -> MatchTable:
        name, refs = await self._university(uow, institution_id)
        if dues is None:
            dues = await application_dues(uow, student_id)
        due = dues.get(institution_id)
        essays = await uow.essays.list_for(student_id)
        alignment = await self._alignments(uow, essays, institution_id)
        placed = {
            s.slot: s.essay_id
            for s in await uow.slots.for_student(student_id, institution_id)
        }
        by_id = {e.id: e for e in essays}
        slots = [
            MatchSlot(
                PS_SLOT,
                None,
                None,
                placed.get(PS_SLOT),
                (),
                True,
                _assigned(_held(by_id, placed.get(PS_SLOT)), None),
            )
        ]
        slots[0] = self._slot(slots[0], essays, alignment, institution_id, None)
        for ref in sorted(refs, key=lambda r: r.position):
            key = supp_slot(ref.position)
            base = MatchSlot(
                key,
                ref.prompt,
                ref.word_limit,
                placed.get(key),
                (),
                ref.required,
                _assigned(_held(by_id, placed.get(key)), ref.word_limit),
            )
            slots.append(self._slot(base, essays, alignment, institution_id, ref))
        return MatchTable(
            institution_id,
            name,
            tuple(slots),
            None if due is None else due.due_utc,
            due is not None and due.predicted,
        )

    @staticmethod
    def _slot(
        slot: MatchSlot,
        essays: list[Essay],
        alignment: dict[UUID, int],
        institution_id: UUID,
        ref: PromptRef | None,
    ) -> MatchSlot:
        wanted = (institution_id, ref.position) if ref is not None else None
        cands: list[MatchCandidate] = []
        for e in essays:
            if slot.slot == PS_SLOT and e.kind != "personal_statement":
                continue
            hit = wanted is not None and any(
                (t.institution_id, t.position) == wanted for t in e.targets
            )
            cands.append(
                MatchCandidate(
                    e.id, e.title, e.kind, e.word_count, alignment.get(e.id), hit
                )
            )
        limit = slot.word_limit
        cands.sort(
            key=lambda c: (
                limit is not None and c.word_count > limit,
                -(c.alignment if c.alignment is not None else -1),
                not c.target_match,
                -c.word_count,
            )
        )
        return MatchSlot(
            slot.slot,
            slot.prompt,
            slot.word_limit,
            slot.essay_id,
            tuple(cands),
            slot.required,
            slot.assigned,
        )

    @staticmethod
    async def _alignments(
        uow: AdmissionUnitOfWork, essays: list[Essay], institution_id: UUID
    ) -> dict[UUID, int]:
        out: dict[UUID, int] = {}
        for e in essays:
            for r in await uow.essay_reviews.list_for_essay(e.id):
                if r.kind == "uni" and r.institution_id == institution_id:
                    payload: dict[str, Any] = r.payload
                    out[e.id] = int(payload.get("alignment", 0))
                    break
        return out
