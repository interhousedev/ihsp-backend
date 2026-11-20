"""Tests & certificates: admin catalog, student entries, staff verification."""

import dataclasses
import datetime as dt
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Final, Literal
from uuid import UUID

from app.modules.admission.application.access import AccessPolicy
from app.modules.admission.application.actor import (
    AdmissionContext,
    can_edit_settings,
)
from app.modules.admission.application.score_certificates import (
    ExamCertificate,
    merge_certificates,
)
from app.modules.admission.domain.errors import (
    AdmissionConflictError,
    AdmissionForbiddenError,
    AdmissionNotFoundError,
    ItemLimitError,
    ScoreInvalidError,
)
from app.modules.admission.domain.permissions import Permission
from app.modules.admission.domain.test_scores import (
    MAX_ENTRIES,
    Score,
    ScoreEntry,
    ScoreEntryDraft,
    ScoreSummary,
    ScoreTest,
    summarise,
    validate_definition,
    validate_entry,
)
from app.modules.admission.ports.repositories import AuditEvent
from app.modules.admission.ports.test_scores import ScoreUnitOfWork
from app.shared.clock import Clock
from app.shared.contracts.certificates import CertificateDirectory
from app.shared.ids import new_id

ScoreUowFactory = Callable[[], ScoreUnitOfWork]
OBJECT: Final = "test_score"
DatedKind = Literal["registration", "day"]
_OPEN: Final = ("planned", "registered")


@dataclass(frozen=True, slots=True)
class ScoreOverview:
    """A student's entries with the best result and superscore of each test."""

    entries: list[ScoreEntry]
    summaries: list[ScoreSummary]
    is_owner: bool
    can_verify: bool
    exams: list[ExamCertificate] = field(default_factory=list)
    """Standard certificates of the platform with no matching test (owner only)."""


@dataclass(frozen=True, slots=True)
class DatedScore:
    """A date of an open entry that belongs on the calendar."""

    entry: ScoreEntry
    test: ScoreTest
    kind: DatedKind
    day: dt.date


class ScoreService:
    """Use cases of the tests & certificates slice."""

    def __init__(
        self,
        uow_factory: ScoreUowFactory,
        access: AccessPolicy,
        clock: Clock,
        certificates: CertificateDirectory | None = None,
    ) -> None:
        """Keep the collaborators."""
        self._uow = uow_factory
        self._access = access
        self._clock = clock
        self._certificates = certificates

    # - - - Catalog - - -

    def is_admin(self, ctx: AdmissionContext) -> bool:
        """Administrators and counselors edit the catalog."""
        return can_edit_settings(ctx, self._clock.now())

    def _require_admin(self, ctx: AdmissionContext) -> None:
        if not self.is_admin(ctx):
            raise AdmissionForbiddenError(params={"permission": "settings:edit"})

    async def catalog(self, ctx: AdmissionContext) -> list[ScoreTest]:
        """Active tests; administrators also see the inactive ones."""
        async with self._uow() as uow:
            return await uow.test_scores.catalog(include_inactive=self.is_admin(ctx))

    async def save_test(
        self, ctx: AdmissionContext, test_id: UUID | None, draft: ScoreTest
    ) -> ScoreTest:
        """Create (`test_id` None) or replace a test definition."""
        self._require_admin(ctx)
        test = dataclasses.replace(draft, id=test_id or new_id())
        validate_definition(test)
        async with self._uow() as uow:
            repo = uow.test_scores
            if test_id and await repo.get_test(test_id) is None:
                raise AdmissionNotFoundError()
            if await repo.key_taken(test.key, except_id=test_id):
                raise AdmissionConflictError(params={"field": "key"})
            saved = await repo.save_test(test)
            await uow.commit()
        return saved

    async def delete_test(self, ctx: AdmissionContext, test_id: UUID) -> None:
        """Delete an unused test; a used one must be deactivated instead."""
        self._require_admin(ctx)
        async with self._uow() as uow:
            if await uow.test_scores.get_test(test_id) is None:
                raise AdmissionNotFoundError()
            if await uow.test_scores.test_in_use(test_id):
                raise AdmissionConflictError(params={"field": "test_id"})
            await uow.test_scores.delete_test(test_id)
            await uow.commit()

    # - - - Entries - - -

    async def overview(
        self, ctx: AdmissionContext, student_id: UUID | None = None
    ) -> ScoreOverview:
        """Entries of the caller or, with PROFILE_READ, of a student in scope."""
        target = student_id or ctx.user_id
        async with self._uow() as uow:
            res = await self._access.require(
                ctx,
                target,
                Permission.PROFILE_READ,
                object_type=OBJECT,
            )
            entries = await uow.test_scores.entries(target)
            tests = {
                t.id: t for t in await uow.test_scores.catalog(include_inactive=True)
            }
            await uow.commit()
        can_verify = False
        exams: list[ExamCertificate] = []
        if not res.owner:
            can_verify = Permission.DOCUMENTS_REVIEW in res.permissions
        elif self._certificates is not None:
            entries, exams = merge_certificates(
                target,
                entries,
                list(tests.values()),
                await self._certificates.for_student(target),
                self._clock.now(),
            )
        by_test: dict[UUID, list[ScoreEntry]] = {}
        for e in entries:
            by_test.setdefault(e.test_id, []).append(e)
        summaries = [
            summarise(tests[i], rows) for i, rows in by_test.items() if i in tests
        ]
        return ScoreOverview(entries, summaries, res.owner, can_verify, exams)

    async def _owner(self, ctx: AdmissionContext) -> None:
        res = await self._access.require(ctx, ctx.user_id, Permission.PROFILE_READ)
        if not res.owner:
            raise AdmissionForbiddenError(params={"permission": "profile:edit"})

    async def _checked(
        self,
        uow: ScoreUnitOfWork,
        ctx: AdmissionContext,
        draft: ScoreEntryDraft,
        keep_test_id: UUID | None = None,
    ) -> tuple[ScoreTest, dict[str, Score], Score | None]:
        test = await uow.test_scores.get_test(draft.test_id)
        if test is None or not (test.active or test.id == keep_test_id):
            raise ScoreInvalidError(params={"field": "test_id"})
        sections, total = validate_entry(test, draft)
        if draft.certificate_document_id:
            doc = await uow.documents.get(draft.certificate_document_id)
            if doc is None or doc.student_id != ctx.user_id:
                raise ScoreInvalidError(params={"field": "certificate_document_id"})
        return test, sections, total

    async def create(self, ctx: AdmissionContext, draft: ScoreEntryDraft) -> ScoreEntry:
        """Add an entry (owner only)."""
        await self._owner(ctx)
        async with self._uow() as uow:
            _, sections, total = await self._checked(uow, ctx, draft)
            if len(await uow.test_scores.entries(ctx.user_id)) >= MAX_ENTRIES:
                raise ItemLimitError(
                    params={"kind": "test_score", "limit": MAX_ENTRIES}
                )
            now = self._clock.now()
            entry = _entry(
                new_id(), ctx.user_id, draft, sections, total, now, now, None, None
            )
            saved = await uow.test_scores.save_entry(entry)
            await uow.commit()
        return saved

    async def update(
        self, ctx: AdmissionContext, entry_id: UUID, draft: ScoreEntryDraft
    ) -> ScoreEntry:
        """Replace an entry (owner only); an edit clears the verification."""
        await self._owner(ctx)
        async with self._uow() as uow:
            old = await self._mine(uow, ctx, entry_id)
            _, sections, total = await self._checked(uow, ctx, draft, old.test_id)
            entry = _entry(
                old.id,
                old.student_id,
                draft,
                sections,
                total,
                old.created_at,
                self._clock.now(),
                None,
                None,
            )
            saved = await uow.test_scores.save_entry(entry)
            await uow.commit()
        return saved

    async def delete(self, ctx: AdmissionContext, entry_id: UUID) -> None:
        """Remove an entry (owner only)."""
        await self._owner(ctx)
        async with self._uow() as uow:
            old = await self._mine(uow, ctx, entry_id)
            await uow.test_scores.delete_entry(old.id)
            await uow.commit()

    async def _mine(
        self, uow: ScoreUnitOfWork, ctx: AdmissionContext, entry_id: UUID
    ) -> ScoreEntry:
        entry = await uow.test_scores.get_entry(entry_id)
        if entry is None or entry.student_id != ctx.user_id:
            raise AdmissionNotFoundError()
        return entry

    async def verify(
        self, ctx: AdmissionContext, entry_id: UUID, verified: bool
    ) -> ScoreEntry:
        """Mark a received result verified or not (staff with DOCUMENTS_REVIEW)."""
        async with self._uow() as uow:
            entry = await uow.test_scores.get_entry(entry_id)
            if entry is None:
                raise AdmissionNotFoundError()
            await self._access.require(
                ctx,
                entry.student_id,
                Permission.DOCUMENTS_REVIEW,
                object_type=OBJECT,
                object_id=entry.id,
            )
            if entry.status != "score_received":
                raise AdmissionConflictError(params={"status": entry.status})
            now = self._clock.now()
            saved = await uow.test_scores.save_entry(
                dataclasses.replace(
                    entry,
                    verified_by=ctx.user_id if verified else None,
                    verified_at=now if verified else None,
                )
            )
            uow.access.audit(
                AuditEvent(
                    action=(
                        "test_score.verified" if verified else "test_score.unverified"
                    ),
                    actor_id=ctx.user_id,
                    student_id=entry.student_id,
                    object_type=OBJECT,
                    object_id=entry.id,
                )
            )
            await uow.commit()
        return saved

    # - - - Calendar - - -

    async def dated(
        self, student_id: UUID, start: dt.date, end: dt.date
    ) -> list[DatedScore]:
        """Registration deadlines and test days of open entries within [start, end]."""
        async with self._uow() as uow:
            entries = await uow.test_scores.entries(student_id)
            tests = {
                t.id: t for t in await uow.test_scores.catalog(include_inactive=True)
            }
        out: list[DatedScore] = []
        for e in entries:
            test = tests.get(e.test_id)
            if test is None or e.status not in _OPEN:
                continue
            if e.status == "planned" and e.registration_deadline:
                out.append(DatedScore(e, test, "registration", e.registration_deadline))
            if e.test_date:
                out.append(DatedScore(e, test, "day", e.test_date))
        return [d for d in out if start <= d.day <= end]


def _entry(
    entry_id: UUID,
    student_id: UUID,
    draft: ScoreEntryDraft,
    sections: dict[str, Score],
    total: object,
    created: dt.datetime,
    updated: dt.datetime,
    verified_by: UUID | None,
    verified_at: dt.datetime | None,
) -> ScoreEntry:
    return ScoreEntry(
        id=entry_id,
        student_id=student_id,
        test_id=draft.test_id,
        status=draft.status,
        test_date=draft.test_date,
        registration_deadline=draft.registration_deadline,
        label=(draft.label or "").strip() or None,
        level=(draft.level or "").strip() or None,
        sections=sections,
        total=total,  # type: ignore[arg-type]
        certificate_document_id=draft.certificate_document_id,
        verification_url=draft.verification_url or None,
        send_note=(draft.send_note or "").strip() or None,
        is_official=draft.is_official,
        verified_by=verified_by,
        verified_at=verified_at,
        created_at=created,
        updated_at=updated,
    )
