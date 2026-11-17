"""SQL repositories of the chooser slice."""

from collections import defaultdict
from collections.abc import Iterable
from uuid import UUID

from app.modules.admission.domain.chooser import (
    AffordabilityCheck,
    CatalogInstitution,
    CatalogScholarship,
    FactView,
    ListEntry,
)
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.infrastructure.orm.applications import (
    AffordabilityCheckRow,
    ListEntryRow,
)
from app.modules.admission.infrastructure.orm.catalog import (
    AidPolicyRow,
    CostOfAttendanceRow,
    FactRow,
    InstitutionRow,
    ScholarshipRow,
    SourceRow,
)
from app.modules.admission.infrastructure.orm.profile import ProfileRow
from app.shared.ids import new_id

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

REVIEWED_CONFIDENCE = ("official", "structured_api")
"""Fact confidences that count as verified."""


def _scholarship(r: ScholarshipRow) -> CatalogScholarship:
    return CatalogScholarship(
        id=r.id,
        name=r.name,
        provider=r.provider,
        institution_id=r.institution_id,
        country=r.country,
        basis=r.basis,
        coverage_min=r.coverage_pct_min,
        coverage_max=r.coverage_pct_max,
        covers=tuple(r.covers or ()),
        url=r.url,
        status=r.status,
        cycle=r.cycle,
    )


class SqlCatalogRepository:
    """Catalog reads (writes are the seed loader's)."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def institutions(
        self, *, country: str | None = None
    ) -> list[CatalogInstitution]:
        """Return non-archived institutions ordered by name."""
        q = select(InstitutionRow).where(InstitutionRow.status != "archived")
        if country:
            q = q.where(InstitutionRow.country == country.upper())
        rows = (await self._s.scalars(q.order_by(InstitutionRow.name))).all()
        return await self._build(rows)

    async def institution(self, institution_id: UUID) -> CatalogInstitution | None:
        """Return one non-archived institution."""
        row = await self._s.get(InstitutionRow, institution_id)
        if row is None or row.status == "archived":
            return None
        return (await self._build([row]))[0]

    async def scholarships(
        self,
        *,
        institution_id: UUID | None = None,
        country: str | None = None,
        basis: str | None = None,
        coverage_min: int | None = None,
    ) -> list[CatalogScholarship]:
        """Return the institution's and the national scholarships, by name."""
        q = select(ScholarshipRow)
        if institution_id is not None:
            q = q.where(ScholarshipRow.institution_id == institution_id)
        if country:
            q = q.where(ScholarshipRow.country == country.upper())
        if basis:
            q = q.where(ScholarshipRow.basis == basis)
        if coverage_min is not None:
            q = q.where(ScholarshipRow.coverage_pct_max >= coverage_min)
        rows = await self._s.scalars(q.order_by(ScholarshipRow.name))
        return [_scholarship(r) for r in rows]

    async def _build(self, rows: Iterable[InstitutionRow]) -> list[CatalogInstitution]:
        rows = list(rows)
        ids = [r.id for r in rows]
        if not ids:
            return []
        facts: dict[UUID, dict[str, FactView]] = defaultdict(dict)
        fq = (
            select(FactRow, SourceRow.url)
            .join(SourceRow, SourceRow.id == FactRow.source_id, isouter=True)
            .where(
                FactRow.entity_kind == "institution",
                FactRow.entity_id.in_(ids),
                FactRow.status == "published",
            )
            .order_by(FactRow.cycle.nulls_first())
        )
        for fact, url in (await self._s.execute(fq)).tuples():
            facts[fact.entity_id][fact.key] = FactView(
                value=fact.value,
                source_url=url,
                year=fact.cycle,
                note=fact.excerpt,
                verified=fact.confidence in REVIEWED_CONFIDENCE
                or fact.reviewer_id is not None,
            )
        coa: dict[UUID, CostOfAttendanceRow] = {}
        cq = (
            select(CostOfAttendanceRow)
            .where(CostOfAttendanceRow.institution_id.in_(ids))
            .order_by(CostOfAttendanceRow.cycle)
        )
        for c in await self._s.scalars(cq):
            coa[c.institution_id] = c
        aid: dict[UUID, AidPolicyRow] = {}
        aq = (
            select(AidPolicyRow)
            .where(AidPolicyRow.institution_id.in_(ids))
            .order_by(AidPolicyRow.cycle)
        )
        for a in await self._s.scalars(aq):
            aid[a.institution_id] = a
        sq = (
            select(ScholarshipRow.institution_id, func.count())
            .where(ScholarshipRow.institution_id.in_(ids))
            .group_by(ScholarshipRow.institution_id)
        )
        counts = dict((await self._s.execute(sq)).tuples().all())
        out = []
        for r in rows:
            cost, policy = coa.get(r.id), aid.get(r.id)
            out.append(
                CatalogInstitution(
                    id=r.id,
                    slug=r.slug,
                    name=r.name,
                    country=r.country,
                    city=r.city,
                    status=r.status,
                    facts=facts.get(r.id, {}),
                    coa_total=cost.total if cost else None,
                    coa_currency=cost.currency if cost else None,
                    aid_basis=policy.intl_need_based if policy else None,
                    merit_available=policy.merit_available if policy else None,
                    scholarship_count=int(counts.get(r.id, 0)),
                    logo_url=r.logo_url,
                    cover_url=r.cover_url,
                    name_local=r.name_local,
                    aliases=tuple(r.aliases or ()),
                    logo_zoom=float(r.logo_zoom),
                    logo_fit=r.logo_fit,
                    logo_aspect=r.logo_aspect,
                )
            )
        return out


def _entry(r: ListEntryRow) -> ListEntry:
    return ListEntry(
        id=r.id,
        student_id=r.student_id,
        institution_id=r.institution_id,
        round=r.round,
        status=r.status,
        bucket=r.bucket,
        notes=r.notes,
        label_override=r.label_override,
        override_note=r.override_note,
        override_by=r.override_by,
        override_at=r.override_at,
        affordability_status=r.affordability_status,
        lock_version=r.lock_version,
        cycle=r.cycle,
    )


def _apply(row: ListEntryRow, e: ListEntry) -> None:
    row.round = e.round
    row.status = e.status
    row.bucket = e.bucket
    row.notes = e.notes
    row.label_override = e.label_override
    row.override_note = e.override_note
    row.override_by = e.override_by
    row.override_at = e.override_at
    row.affordability_status = e.affordability_status
    row.cycle = e.cycle


def _check(r: AffordabilityCheckRow) -> AffordabilityCheck:
    return AffordabilityCheck(
        list_entry_id=r.list_entry_id,
        coa_total=r.coa_total,
        confirmed_aid=r.confirmed_aid,
        estimated_aid=r.estimated_aid,
        gap=r.gap,
        status=r.status,
        requested_sign_off_at=r.requested_sign_off_at,
        signed_off_by=r.signed_off_by,
        signed_off_at=r.signed_off_at,
        sign_off_note=r.sign_off_note,
    )


class SqlListRepository:
    """The student's list and its affordability checks."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the open session."""
        self._s = session

    async def entries(self, student_id: UUID) -> list[ListEntry]:
        """Return a student's entries, oldest first."""
        rows = await self._s.scalars(
            select(ListEntryRow)
            .where(ListEntryRow.student_id == student_id)
            .order_by(ListEntryRow.id)
        )
        return [_entry(r) for r in rows]

    async def entry(self, entry_id: UUID) -> ListEntry | None:
        """Return one entry."""
        row = await self._s.get(ListEntryRow, entry_id)
        return _entry(row) if row else None

    async def find(self, student_id: UUID, institution_id: UUID) -> ListEntry | None:
        """Return the entry of an institution on a student's list."""
        row = await self._s.scalar(
            select(ListEntryRow).where(
                ListEntryRow.student_id == student_id,
                ListEntryRow.institution_id == institution_id,
            )
        )
        return _entry(row) if row else None

    async def add(self, entry: ListEntry) -> ListEntry:
        """Insert an entry."""
        row = ListEntryRow(
            id=new_id(),
            student_id=entry.student_id,
            institution_id=entry.institution_id,
            lock_version=0,
        )
        _apply(row, entry)
        self._s.add(row)
        await self._s.flush()
        return _entry(row)

    async def save(self, entry: ListEntry, *, expected_lock: int) -> ListEntry:
        """Write an entry; `AdmissionConflictError` if `lock_version` moved."""
        row = await self._s.get(ListEntryRow, entry.id, with_for_update=True)
        if row is None or row.lock_version != expected_lock:
            raise AdmissionConflictError()
        _apply(row, entry)
        row.lock_version += 1
        await self._s.flush()
        return _entry(row)

    async def delete(self, entry_id: UUID) -> None:
        """Remove an entry."""
        row = await self._s.get(ListEntryRow, entry_id)
        if row is not None:
            await self._s.delete(row)
            await self._s.flush()

    async def budget_band(self, student_id: UUID) -> str | None:
        """Return the student's stated yearly budget band."""
        return await self._s.scalar(
            select(ProfileRow.budget_band).where(ProfileRow.student_id == student_id)
        )

    async def affordability(self, entry_id: UUID) -> AffordabilityCheck | None:
        """Return the affordability check of an entry."""
        row = await self._s.scalar(
            select(AffordabilityCheckRow).where(
                AffordabilityCheckRow.list_entry_id == entry_id
            )
        )
        return _check(row) if row else None

    async def save_affordability(self, check: AffordabilityCheck) -> None:
        """Insert or replace the check of an entry."""
        row = await self._s.scalar(
            select(AffordabilityCheckRow).where(
                AffordabilityCheckRow.list_entry_id == check.list_entry_id
            )
        )
        if row is None:
            row = AffordabilityCheckRow(
                id=new_id(), list_entry_id=check.list_entry_id, lock_version=0
            )
            self._s.add(row)
        row.coa_total = check.coa_total
        row.confirmed_aid = check.confirmed_aid
        row.estimated_aid = check.estimated_aid
        row.gap = check.gap
        row.status = check.status
        row.requested_sign_off_at = check.requested_sign_off_at
        row.signed_off_by = check.signed_off_by
        row.signed_off_at = check.signed_off_at
        row.sign_off_note = check.sign_off_note
        await self._s.flush()
