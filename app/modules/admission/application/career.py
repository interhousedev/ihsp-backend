"""Career exploration: the inventory, the shortlist, majors and minors, the spike.

Questions and majors are rows administrators edit; the student edits only their
own plan, staff in scope read it. AI drafts live in `career_suggest`.
"""

from collections.abc import Awaitable, Callable, Sequence
from dataclasses import replace
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext, can_edit_settings
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.domain.career import (
    EVIDENCE_MAX,
    GAPS_MAX,
    REASON_MAX,
    SHORTLIST_MAX,
    SUMMARY_MAX,
    TITLE_MAX,
    CareerMajor,
    CareerPlan,
    CareerQuestion,
    CareerSection,
    Spike,
    SpikeEvidence,
    check_text,
    choose_majors,
    clean_answers,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    InvalidAnswerError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id

_Change = Callable[[AdmissionUnitOfWork, CareerPlan], Awaitable[CareerPlan]]


async def owner_plan(uow: AdmissionUnitOfWork, student_id: UUID) -> CareerPlan:
    """The stored plan, or an empty one not yet saved."""
    return await uow.career.plan(student_id) or CareerPlan(student_id=student_id)


class CareerService:
    """Reads and edits of the inventory, the taxonomy and a student's plan."""

    def __init__(
        self, uow_factory: UowFactory, access: AccessPolicy, clock: Clock
    ) -> None:
        """Keep the transaction factory, the access policy and the clock."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})

    def require_editor(self, ctx: AdmissionContext) -> None:
        """Refuse anyone but an administrator or a live counselor."""
        if not can_edit_settings(ctx, self._clock.now()):
            raise AdmissionForbiddenError(params={"permission": "career:edit"})

    async def questions(
        self, *, include_inactive: bool = False
    ) -> list[CareerQuestion]:
        """List the inventory; inactive rows only for administrators."""
        async with self._uow() as uow:
            return await uow.career.questions(active_only=not include_inactive)

    async def majors(self, *, include_inactive: bool = False) -> list[CareerMajor]:
        """The majors taxonomy."""
        async with self._uow() as uow:
            return await uow.career.majors(active_only=not include_inactive)

    async def plan(self, ctx: AdmissionContext, student_id: UUID) -> CareerPlan:
        """The student's plan; staff need activities read in scope."""
        await self._access.require(
            ctx, student_id, Permission.ACTIVITIES_READ, object_type="career"
        )
        async with self._uow() as uow:
            plan = await owner_plan(uow, student_id)
            await uow.commit()
        return plan

    async def _edit(
        self, ctx: AdmissionContext, lock_version: int, change: _Change
    ) -> CareerPlan:
        await self._owner(ctx)
        async with self._uow() as uow:
            current = await owner_plan(uow, ctx.user_id)
            plan = await change(uow, replace(current, lock_version=lock_version))
            saved = await uow.career.save_plan(plan)
            await uow.commit()
        return saved

    async def save_answers(
        self, ctx: AdmissionContext, answers: dict[str, str], lock_version: int
    ) -> CareerPlan:
        """Replace the inventory answers (keys are question ids)."""

        async def change(uow: AdmissionUnitOfWork, plan: CareerPlan) -> CareerPlan:
            known = {str(q.id) for q in await uow.career.questions(active_only=True)}
            clean = {k: nfc(v) for k, v in clean_answers(answers, known).items()}
            return replace(plan, answers=clean)

        return await self._edit(ctx, lock_version, change)

    async def shortlist(
        self, ctx: AdmissionContext, titles: Sequence[str], lock_version: int
    ) -> CareerPlan:
        """Mark which suggested professions the student keeps (at most five)."""
        chosen = {t.strip().casefold() for t in titles}
        if len(chosen) > SHORTLIST_MAX:
            raise InvalidAnswerError(params={"question": "shortlist"})

        async def change(uow: AdmissionUnitOfWork, plan: CareerPlan) -> CareerPlan:
            known = {p.title.casefold() for p in plan.professions}
            if not chosen <= known:
                raise InvalidAnswerError(params={"question": "shortlist"})
            return replace(
                plan,
                professions=[
                    replace(p, shortlisted=p.title.casefold() in chosen)
                    for p in plan.professions
                ],
            )

        return await self._edit(ctx, lock_version, change)

    async def choose(
        self,
        ctx: AdmissionContext,
        majors: Sequence[str],
        minors: Sequence[str],
        lock_version: int,
    ) -> CareerPlan:
        """Store the chosen majors and minors (codes of the taxonomy)."""

        async def change(uow: AdmissionUnitOfWork, plan: CareerPlan) -> CareerPlan:
            taxonomy = {m.code: m for m in await uow.career.majors(active_only=True)}
            picked, minor = choose_majors(list(majors), list(minors), taxonomy)
            return replace(plan, majors=picked, minors=minor)

        return await self._edit(ctx, lock_version, change)

    async def confirm_spike(
        self,
        ctx: AdmissionContext,
        title: str,
        summary: str,
        evidence: Sequence[tuple[UUID, str]],
        gaps: Sequence[str],
        lock_version: int,
    ) -> CareerPlan:
        """Store the spike as the student wrote or accepted it, confirmed now."""
        if len(evidence) > EVIDENCE_MAX or len(gaps) > GAPS_MAX:
            raise InvalidAnswerError(params={"question": "spike"})
        spike_title = nfc(check_text("title", title, TITLE_MAX))
        spike_summary = nfc(check_text("summary", summary, SUMMARY_MAX))
        notes = [(i, nfc(check_text("note", n, REASON_MAX))) for i, n in evidence]
        clean_gaps = tuple(nfc(check_text("gap", g, REASON_MAX)) for g in gaps)

        async def change(uow: AdmissionUnitOfWork, plan: CareerPlan) -> CareerPlan:
            own = {i.id for i in await uow.items.list_for(ctx.user_id)}
            if any(item_id not in own for item_id, _ in notes):
                raise AdmissionNotFoundError()
            spike = Spike(
                title=spike_title,
                summary=spike_summary,
                evidence=tuple(SpikeEvidence(i, n) for i, n in notes),
                gaps=clean_gaps,
                confirmed_at=self._clock.now(),
            )
            return replace(plan, spike=spike)

        return await self._edit(ctx, lock_version, change)

    async def save_question(
        self,
        ctx: AdmissionContext,
        question_id: UUID | None,
        section: CareerSection,
        prompt: dict[str, str],
        sort_order: int,
        active: bool,
    ) -> CareerQuestion:
        """Add or edit an inventory question (administrators)."""
        self.require_editor(ctx)
        question = CareerQuestion(
            id=question_id or new_id(),
            section=section,
            prompt={k: nfc(v) for k, v in prompt.items()},
            sort_order=sort_order,
            active=active,
        )
        question.validate()
        async with self._uow() as uow:
            if question_id and await uow.career.get_question(question_id) is None:
                raise AdmissionNotFoundError()
            saved = await uow.career.save_question(question)
            self._audit(uow, ctx, "career.question_saved", "career_question", saved.id)
            await uow.commit()
        return saved

    async def save_major(
        self,
        ctx: AdmissionContext,
        major_id: UUID | None,
        code: str,
        area: str,
        name: dict[str, str],
        minor_ok: bool,
        sort_order: int,
        active: bool,
    ) -> CareerMajor:
        """Add or edit a major of the taxonomy (administrators)."""
        self.require_editor(ctx)
        major = CareerMajor(
            id=major_id or new_id(),
            code=code,
            area=nfc(area),
            name={k: nfc(v) for k, v in name.items()},
            minor_ok=minor_ok,
            sort_order=sort_order,
            active=active,
        )
        major.validate()
        async with self._uow() as uow:
            if major_id and await uow.career.get_major(major_id) is None:
                raise AdmissionNotFoundError()
            saved = await uow.career.save_major(major)
            self._audit(uow, ctx, "career.major_saved", "career_major", saved.id)
            await uow.commit()
        return saved

    @staticmethod
    def _audit(
        uow: AdmissionUnitOfWork,
        ctx: AdmissionContext,
        action: str,
        object_type: str,
        object_id: UUID,
    ) -> None:
        uow.access.audit(
            AuditEvent(
                action=action,
                actor_id=ctx.user_id,
                student_id=None,
                object_type=object_type,
                object_id=object_id,
                meta={},
            )
        )
