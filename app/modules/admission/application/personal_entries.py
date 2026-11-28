"""A student's own finds in the opportunity plan ("not in the catalog").

The entry belongs to the caller; the owner is never taken from input. Before an
entry is saved its dedup keys are matched against the published catalog: a match
is planned as the catalog entry instead. With `propose` the find also goes to the
moderators through `OpportunityService.submit`; approval replaces it with a
normal plan entry (`OpportunityService.review`). Links are checked as text and
never fetched.
"""

import dataclasses
import datetime as dt
from dataclasses import dataclass
from typing import Final, cast
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import AdmissionContext
from app.modules.admission.application.item_opportunity import dedup_keys
from app.modules.admission.application.opportunities import (
    OpportunityService,
    OppUowFactory,
)
from app.modules.admission.domain.errors import (
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ItemLimitError,
)
from app.modules.admission.domain.opportunities import (
    MAX_PLAN_ITEMS,
    OpportunityDraft,
    OpportunityKind,
    OpportunitySubmission,
)
from app.modules.admission.domain.personal_entries import (
    PERSONAL_ADD_LIMIT,
    PersonalDraft,
    PersonalEntry,
    PersonalOrigin,
    PlanDuplicateError,
    dedup_key,
)
from app.shared.base_error import ValidationFailedError
from app.shared.clock import Clock
from app.shared.ids import new_id
from app.shared.rate_limit import RateLimiter

_DAY: Final = 86400


@dataclass(frozen=True, slots=True)
class PersonalAdded:
    """Result of an add: the new entry, or the catalog entry planned instead."""

    entry: PersonalEntry | None = None
    planned_opportunity_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class Proposal:
    """The moderation state of a find sent to the catalog."""

    submission_id: UUID
    status: str


def _clean(draft: PersonalDraft) -> PersonalDraft:
    """Trim text fields; empty optional text becomes None."""

    def opt(value: str | None) -> str | None:
        return (value or "").strip() or None

    return dataclasses.replace(
        draft,
        title=draft.title.strip(),
        provider=opt(draft.provider),
        url=opt(draft.url),
        summary=opt(draft.summary),
        planned_term=opt(draft.planned_term),
        note=opt(draft.note),
    )


def personal_key(draft: PersonalDraft) -> str:
    """The stored dedup key of a find (same rules as catalog proposals)."""
    return dedup_key(dedup_keys(draft.title, draft.provider, draft.url))


class PersonalEntryService:
    """Add, update, delete and list the caller's own finds."""

    def __init__(
        self,
        uow_factory: OppUowFactory,
        access: AccessPolicy,
        opportunities: OpportunityService,
        clock: Clock,
        limiter: RateLimiter,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._opportunities = opportunities
        self._clock = clock
        self._limiter = limiter

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.resolve(ctx, ctx.user_id)
        if not res.owner or not ctx.admission.is_applicant:
            raise AdmissionForbiddenError(params={"permission": "list:edit"})

    async def _check(self, draft: PersonalDraft) -> PersonalDraft:
        draft = _clean(draft)
        bad = draft.problems()
        if bad:
            raise ValidationFailedError(params={"field": bad[0]})
        if draft.planned_grade is not None and draft.planned_grade not in (
            await self._access.school_grades()
        ):
            raise ValidationFailedError(params={"field": "planned_grade"})
        return draft

    async def entries(self, ctx: AdmissionContext) -> list[PersonalEntry]:
        """The caller's finds, oldest first."""
        await self._owner(ctx)
        async with self._uow() as uow:
            return await uow.opportunities.personal_entries(ctx.user_id)

    async def add(
        self,
        ctx: AdmissionContext,
        draft: PersonalDraft,
        *,
        origin: PersonalOrigin = "web",
        propose: bool = False,
    ) -> PersonalAdded:
        """Save a find, or plan the catalog entry it matches.

        Raises `PlanDuplicateError` (params `entry_id`) when the caller already has
        it, `ItemLimitError` past the joint limit of catalog and personal entries,
        and `RateLimitedError` past `PERSONAL_ADD_LIMIT` additions per day.
        """
        await self._owner(ctx)
        draft = await self._check(draft)
        keys = dedup_keys(draft.title, draft.provider, draft.url)
        key = dedup_key(keys)
        async with self._uow() as uow:
            repo = uow.opportunities
            match = next(
                (
                    o.id
                    for o in await repo.list_published()
                    if keys & dedup_keys(o.draft.title, o.draft.provider, o.draft.url)
                ),
                None,
            )
            if match is None:
                twin = await repo.personal_by_key(ctx.user_id, key)
                if twin is not None:
                    raise PlanDuplicateError(params={"entry_id": str(twin.id)})
                count = len(await repo.plan(ctx.user_id)) + len(
                    await repo.personal_entries(ctx.user_id)
                )
                if count >= MAX_PLAN_ITEMS:
                    raise ItemLimitError(params={"limit": MAX_PLAN_ITEMS})
        if match is not None:
            await self._opportunities.save_to_plan(
                ctx,
                match,
                planned_grade=draft.planned_grade,
                planned_term=draft.planned_term,
                note=draft.note,
            )
            return PersonalAdded(planned_opportunity_id=match)
        await self._limiter.hit(
            f"admission:personal_add:{ctx.user_id}",
            limit=PERSONAL_ADD_LIMIT,
            window_seconds=_DAY,
        )
        submission = await self._propose(ctx, draft) if propose else None
        now = self._clock.now()
        async with self._uow() as uow:
            saved = await uow.opportunities.add_personal(
                PersonalEntry(
                    id=new_id(),
                    student_id=ctx.user_id,
                    kind=cast(OpportunityKind, draft.kind),
                    title=draft.title,
                    provider=draft.provider,
                    url=draft.url,
                    summary=draft.summary,
                    registration_deadline=draft.registration_deadline,
                    starts_on=draft.starts_on,
                    ends_on=draft.ends_on,
                    planned_grade=draft.planned_grade,
                    planned_term=draft.planned_term,
                    note=draft.note,
                    origin=origin,
                    dedup_key=key,
                    created_at=now,
                    updated_at=now,
                    submission_id=submission.id if submission else None,
                )
            )
            await uow.commit()
        return PersonalAdded(entry=saved)

    async def _propose(
        self, ctx: AdmissionContext, draft: PersonalDraft
    ) -> OpportunitySubmission:
        """Send the find to the moderators (same limit and checks as a proposal)."""
        days = (draft.registration_deadline,)
        return await self._opportunities.submit(
            ctx,
            OpportunityDraft(
                kind=cast(OpportunityKind, draft.kind),
                title=draft.title,
                summary=draft.summary,
                url=draft.url,
                provider=draft.provider,
                registration_deadlines=tuple(d for d in days if d is not None),
                starts_on=draft.starts_on,
                note=draft.note,
            ),
        )

    async def update(
        self,
        ctx: AdmissionContext,
        entry_id: UUID,
        draft: PersonalDraft,
        *,
        lock_version: int,
    ) -> PersonalEntry:
        """Change a find of the caller; another student's id is not found."""
        await self._owner(ctx)
        draft = await self._check(draft)
        async with self._uow() as uow:
            repo = uow.opportunities
            current = await repo.get_personal(ctx.user_id, entry_id)
            if current is None:
                raise AdmissionNotFoundError()
            saved = await repo.save_personal(
                dataclasses.replace(
                    current,
                    kind=cast(OpportunityKind, draft.kind),
                    title=draft.title,
                    provider=draft.provider,
                    url=draft.url,
                    summary=draft.summary,
                    registration_deadline=draft.registration_deadline,
                    starts_on=draft.starts_on,
                    ends_on=draft.ends_on,
                    planned_grade=draft.planned_grade,
                    planned_term=draft.planned_term,
                    note=draft.note,
                    dedup_key=personal_key(draft),
                    updated_at=self._clock.now(),
                ),
                expected_lock=lock_version,
            )
            await uow.commit()
        return saved

    async def delete(self, ctx: AdmissionContext, entry_id: UUID) -> None:
        """Remove a find of the caller; a sent proposal stays in moderation."""
        await self._owner(ctx)
        async with self._uow() as uow:
            if not await uow.opportunities.delete_personal(ctx.user_id, entry_id):
                raise AdmissionNotFoundError()
            await uow.commit()

    async def proposals(self, entries: list[PersonalEntry]) -> dict[UUID, Proposal]:
        """Moderation state per entry id, for entries that were proposed.

        No access check: the caller already read `entries` through one.
        """
        sent = [e for e in entries if e.submission_id is not None]
        if not sent:
            return {}
        out: dict[UUID, Proposal] = {}
        async with self._uow() as uow:
            for e in sent:
                sub_id = cast(UUID, e.submission_id)
                sub = await uow.opportunities.get_submission(sub_id)
                if sub is not None:
                    out[e.id] = Proposal(sub_id, sub.status)
        return out


def upcoming_personal(
    entries: list[PersonalEntry], start: dt.date, end: dt.date
) -> list[tuple[PersonalEntry, str, dt.date]]:
    """Dated events `(entry, kind, day)` of finds within [start, end]."""
    return [(e, k, d) for e in entries for k, d in e.dates if start <= d <= end]


__all__ = [
    "PersonalAdded",
    "PersonalEntryService",
    "Proposal",
    "personal_key",
    "upcoming_personal",
]
