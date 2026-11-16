"""Goal plan: dated milestones, optionally linked to an item (§9)."""

from collections.abc import Mapping, Sequence
from dataclasses import replace
from datetime import date
from typing import Any, Final
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.review_checks import nfc
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ItemLimitError,
)
from app.modules.admission.domain.goal_plan import MAX_MILESTONES, GoalMilestone
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.ports.unit_of_work import AdmissionUnitOfWork, UowFactory
from app.shared.clock import Clock
from app.shared.ids import new_id

EDITABLE: Final = frozenset(
    {"title", "item_id", "due_month", "target_value", "status", "sort_order"}
)


def _month(value: date | None) -> date | None:
    return value.replace(day=1) if value else None


class GoalPlanService:
    """CRUD of a student's milestones; only the owner edits, staff read in scope."""

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

    async def _check_item(
        self, uow: AdmissionUnitOfWork, ctx: AdmissionContext, item_id: UUID | None
    ) -> None:
        if item_id is None:
            return
        item = await uow.items.get(item_id)
        if item is None or item.student_id != ctx.user_id:
            raise AdmissionNotFoundError()

    async def list(
        self, ctx: AdmissionContext, student_id: UUID
    ) -> list[GoalMilestone]:
        """Return the student's milestones in display order."""
        await self._access.require(
            ctx, student_id, Permission.ACTIVITIES_READ, object_type="goal_plan"
        )
        async with self._uow() as uow:
            rows = await uow.goals.list_for(student_id)
            await uow.commit()
        return rows

    async def create(
        self, ctx: AdmissionContext, draft: GoalMilestone
    ) -> GoalMilestone:
        """Add a milestone at the end; at most 12 per student."""
        await self._owner(ctx)
        milestone = replace(
            draft,
            id=new_id(),
            student_id=ctx.user_id,
            title=nfc(draft.title).strip(),
            due_month=_month(draft.due_month),
            source="manual",
            lock_version=0,
        )
        milestone.done_at = self._clock.now() if milestone.status == "done" else None
        milestone.validate()
        async with self._uow() as uow:
            await self._check_item(uow, ctx, milestone.item_id)
            existing = await uow.goals.list_for(ctx.user_id)
            if len(existing) >= MAX_MILESTONES:
                raise ItemLimitError(
                    params={"kind": "milestone", "limit": MAX_MILESTONES}
                )
            milestone.sort_order = max((m.sort_order for m in existing), default=-1) + 1
            stored = await uow.goals.add(milestone)
            await uow.commit()
        return stored

    async def update(
        self,
        ctx: AdmissionContext,
        milestone_id: UUID,
        changes: Mapping[str, Any],
        lock_version: int,
    ) -> GoalMilestone:
        """Change fields; a stale `lock_version` is a conflict."""
        if set(changes) - EDITABLE:
            raise AdmissionForbiddenError(params={"permission": "activities:edit"})
        await self._owner(ctx)
        async with self._uow() as uow:
            current = await uow.goals.get(milestone_id)
            if current is None or current.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            if current.lock_version != lock_version:
                raise AdmissionConflictError()
            fields = dict(changes)
            if "title" in fields:
                fields["title"] = nfc(fields["title"]).strip()
            if "due_month" in fields:
                fields["due_month"] = _month(fields["due_month"])
            updated = replace(current, **fields)
            if updated.status != current.status:
                updated.done_at = (
                    self._clock.now() if updated.status == "done" else None
                )
            updated.validate()
            await self._check_item(uow, ctx, updated.item_id)
            stored = await uow.goals.update(updated)
            await uow.commit()
        return stored

    async def delete(self, ctx: AdmissionContext, milestone_id: UUID) -> None:
        """Delete one of the caller's milestones."""
        await self._owner(ctx)
        async with self._uow() as uow:
            current = await uow.goals.get(milestone_id)
            if current is None or current.student_id != ctx.user_id:
                raise AdmissionNotFoundError()
            await uow.goals.delete(milestone_id)
            await uow.commit()

    async def replace(
        self, ctx: AdmissionContext, drafts: Sequence[GoalMilestone]
    ) -> Sequence[GoalMilestone]:
        """Replace the whole plan with `drafts` in the given order (at most 12).

        A draft whose id is one of the caller's milestones keeps that id, its
        source and its done date while the status stays; other drafts are new.
        """
        await self._owner(ctx)
        if len(drafts) > MAX_MILESTONES:
            raise ItemLimitError(params={"kind": "milestone", "limit": MAX_MILESTONES})
        async with self._uow() as uow:
            old = {m.id: m for m in await uow.goals.list_for(ctx.user_id)}
            kept = set(old)
            fresh: list[GoalMilestone] = []
            for position, draft in enumerate(drafts):
                before = old.pop(draft.id, None)
                milestone = replace(
                    draft,
                    id=before.id if before else new_id(),
                    student_id=ctx.user_id,
                    title=nfc(draft.title).strip(),
                    due_month=_month(draft.due_month),
                    source=before.source if before else "manual",
                    sort_order=position,
                    lock_version=0,
                )
                if before and before.status == milestone.status:
                    milestone.done_at = before.done_at
                else:
                    milestone.done_at = (
                        self._clock.now() if milestone.status == "done" else None
                    )
                milestone.validate()
                await self._check_item(uow, ctx, milestone.item_id)
                fresh.append(milestone)
            for milestone_id in kept:
                await uow.goals.delete(milestone_id)
            stored = [await uow.goals.add(m) for m in fresh]
            await uow.commit()
        return stored
