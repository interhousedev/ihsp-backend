"""The ONE opportunities catalog: admission's table with its audience."""

from uuid import UUID

from app.modules.activities.infrastructure.orm.tables import EventRow
from app.modules.activities.ports.gateways import CatalogEntry
from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.opportunities import OpportunityDraft
from app.modules.admission.infrastructure.orm.opp_social import OppCommentRow, OrgRow
from app.modules.admission.infrastructure.orm.opportunities import (
    OpportunityPlanEntryRow,
    OpportunityRow,
    OpportunityTaxonomyRow,
)
from app.shared.ids import new_id

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.ext.asyncio import AsyncSession


def _entry(r: OpportunityRow) -> CatalogEntry:
    return CatalogEntry(
        id=r.id,
        draft=OpportunityDraft.from_payload(r.payload),
        audience=frozenset(r.audience or ()),
        archived=r.archived,
        lock_version=r.lock_version,
    )


class SqlOpportunityCatalog:
    """`OpportunityCatalog` over admission's `opportunities` table."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the database session."""
        self._s = session

    async def get(self, opportunity_id: UUID) -> CatalogEntry | None:
        """One entry."""
        row = await self._s.get(OpportunityRow, opportunity_id)
        return _entry(row) if row else None

    async def list_all(self) -> list[CatalogEntry]:
        """Every entry, newest first."""
        rows = await self._s.scalars(
            select(OpportunityRow).order_by(OpportunityRow.created_at.desc())
        )
        return [_entry(r) for r in rows]

    async def references_ok(self, draft: OpportunityDraft) -> str | None:
        """The first invalid reference field (subjects, course, ...) or None."""
        if draft.subject_ids:
            found = await self._s.scalar(
                select(func.count())
                .select_from(OpportunityTaxonomyRow)
                .where(
                    OpportunityTaxonomyRow.id.in_(draft.subject_ids),
                    OpportunityTaxonomyRow.level == "subject",
                )
            )
            if found != len(set(draft.subject_ids)):
                return "subject_ids"
        if draft.org_id is not None and await self._s.get(OrgRow, draft.org_id) is None:
            return "org_id"
        courses = {draft.lms_course_id} | {m.lms_course_id for m in draft.materials}
        for course_id in courses - {None}:
            hit = await self._s.scalar(
                text("SELECT 1 FROM lms.courses WHERE id = :id"), {"id": course_id}
            )
            if hit is None:
                return "lms_course_id"
        return None

    async def apply(
        self,
        draft: OpportunityDraft,
        audience: frozenset[str],
        *,
        target_id: UUID | None,
        by: UUID,
    ) -> UUID:
        """Create or overwrite an entry; an update bumps the lock version."""
        payload = draft.to_payload()
        surfaces = sorted(audience)
        if target_id is not None:
            row = await self._s.get(OpportunityRow, target_id)
            if row is None:
                raise AdmissionConflictError()
            row.kind = draft.kind
            row.title = payload["title"]
            row.payload = payload
            row.subject_ids = payload["subject_ids"]
            row.audience = surfaces
            row.lock_version = row.lock_version + 1
        else:
            row = OpportunityRow(
                id=new_id(),
                kind=draft.kind,
                title=payload["title"],
                payload=payload,
                subject_ids=payload["subject_ids"],
                created_by=by,
                audience=surfaces,
            )
            self._s.add(row)
        await self._s.flush()
        return row.id

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        """Hide or restore."""
        await self._s.execute(
            update(OpportunityRow)
            .where(OpportunityRow.id == opportunity_id)
            .values(archived=archived)
        )

    async def in_use(self, opportunity_id: UUID) -> bool:
        """Whether student plans, comments or club events refer to it."""
        for model, column in (
            (OpportunityPlanEntryRow, OpportunityPlanEntryRow.opportunity_id),
            (OppCommentRow, OppCommentRow.opportunity_id),
            (EventRow, EventRow.opportunity_id),
        ):
            hit = await self._s.scalar(
                select(model.id).where(column == opportunity_id).limit(1)
            )
            if hit is not None:
                return True
        return False

    async def delete(self, opportunity_id: UUID) -> None:
        """Remove an unused entry."""
        await self._s.execute(
            delete(OpportunityRow).where(OpportunityRow.id == opportunity_id)
        )
