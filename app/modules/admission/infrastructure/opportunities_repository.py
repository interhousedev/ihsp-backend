"""SQL repository of the opportunities slice."""

import datetime as dt
from typing import Any
from uuid import UUID

from app.modules.admission.domain.errors import AdmissionConflictError
from app.modules.admission.domain.opportunities import (
    ItemOpportunityLink,
    Opportunity,
    OpportunityDraft,
    OpportunitySubmission,
    PlanEntry,
    TaxonomyNode,
)
from app.modules.admission.infrastructure.orm.item_opportunity import (
    ItemOpportunityLinkRow,
)
from app.modules.admission.infrastructure.orm.opportunities import (
    OpportunityAiPlanRow,
    OpportunityPlanEntryRow,
    OpportunityRow,
    OpportunitySubmissionRow,
    OpportunityTaxonomyRow,
)
from app.shared.ids import new_id

from sqlalchemy import delete, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _node(r: OpportunityTaxonomyRow) -> TaxonomyNode:
    return TaxonomyNode(
        id=r.id,
        level=r.level,  # type: ignore[arg-type]
        parent_id=r.parent_id,
        names=dict(r.names),
        position=r.position,
    )


def _opp(r: OpportunityRow) -> Opportunity:
    return Opportunity(
        id=r.id,
        draft=OpportunityDraft.from_payload(r.payload),
        created_by=r.created_by,
        created_at=r.created_at,
        updated_at=r.updated_at,
        archived=r.archived,
        lock_version=r.lock_version,
    )


def _sub(r: OpportunitySubmissionRow) -> OpportunitySubmission:
    return OpportunitySubmission(
        id=r.id,
        target_id=r.target_id,
        payload=dict(r.payload),
        note=r.note,
        status=r.status,  # type: ignore[arg-type]
        submitted_by=r.submitted_by,
        submitter_role=r.submitter_role,  # type: ignore[arg-type]
        created_at=r.created_at,
        lock_version=r.lock_version,
        reviewed_by=r.reviewed_by,
        reviewed_at=r.reviewed_at,
        reason=r.reason,
        applied_id=r.applied_id,
    )


def _entry(r: OpportunityPlanEntryRow) -> PlanEntry:
    return PlanEntry(
        id=r.id,
        student_id=r.student_id,
        opportunity_id=r.opportunity_id,
        planned_grade=r.planned_grade,
        planned_term=r.planned_term,
        note=r.note,
        created_at=r.created_at,
    )


class SqlOpportunityRepository:
    """Rows of the opportunities slice."""

    def __init__(self, session: AsyncSession) -> None:
        """Keep the session."""
        self._s = session

    async def taxonomy(self) -> list[TaxonomyNode]:
        """Every node."""
        q = select(OpportunityTaxonomyRow).order_by(
            OpportunityTaxonomyRow.position, OpportunityTaxonomyRow.id
        )
        return [_node(r) for r in await self._s.scalars(q)]

    async def get_node(self, node_id: UUID) -> TaxonomyNode | None:
        """One node."""
        row = await self._s.get(OpportunityTaxonomyRow, node_id)
        return _node(row) if row else None

    async def save_node(self, node: TaxonomyNode) -> TaxonomyNode:
        """Insert or update a node."""
        row = await self._s.get(OpportunityTaxonomyRow, node.id)
        if row is None:
            row = OpportunityTaxonomyRow(
                id=node.id,
                level=node.level,
                parent_id=node.parent_id,
                names=node.names,
                position=node.position,
            )
            self._s.add(row)
        else:
            row.parent_id = node.parent_id
            row.names = node.names
            row.position = node.position
        await self._s.flush()
        return node

    async def delete_node(self, node_id: UUID) -> None:
        """Delete a node and its children (cascade)."""
        await self._s.execute(
            delete(OpportunityTaxonomyRow).where(OpportunityTaxonomyRow.id == node_id)
        )

    async def node_in_use(self, node_ids: list[UUID]) -> bool:
        """Whether any entry (live or archived) lists one of the subjects."""
        rows = await self._s.scalars(select(OpportunityRow.subject_ids))
        wanted = {str(n) for n in node_ids}
        return any(wanted & set(ids or []) for ids in rows)

    async def list_published(self) -> list[Opportunity]:
        """Live entries."""
        q = select(OpportunityRow).where(OpportunityRow.archived.is_(False))
        return [_opp(r) for r in await self._s.scalars(q)]

    async def get(self, opportunity_id: UUID) -> Opportunity | None:
        """One entry, live or archived."""
        row = await self._s.get(OpportunityRow, opportunity_id)
        return _opp(row) if row else None

    async def get_many(self, opportunity_ids: list[UUID]) -> list[Opportunity]:
        """The entries with these ids, live or archived; unknown ids are skipped."""
        if not opportunity_ids:
            return []
        q = select(OpportunityRow).where(OpportunityRow.id.in_(opportunity_ids))
        return [_opp(r) for r in await self._s.scalars(q)]

    async def apply(
        self, draft: OpportunityDraft, *, target_id: UUID | None, by: UUID
    ) -> UUID:
        """Create or overwrite an entry from an approved draft."""
        payload = draft.to_payload()
        subjects = payload["subject_ids"]
        if target_id is not None:
            row = await self._s.get(OpportunityRow, target_id)
            if row is None:
                raise AdmissionConflictError()
            row.kind = draft.kind
            row.title = payload["title"]
            row.payload = payload
            row.subject_ids = subjects
            row.lock_version = row.lock_version + 1
        else:
            row = OpportunityRow(
                id=new_id(),
                kind=draft.kind,
                title=payload["title"],
                payload=payload,
                subject_ids=subjects,
                created_by=by,
            )
            self._s.add(row)
        await self._s.flush()
        return row.id

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        """Hide or show an entry."""
        await self._s.execute(
            update(OpportunityRow)
            .where(OpportunityRow.id == opportunity_id)
            .values(archived=archived)
        )

    async def add_submission(
        self, submission: OpportunitySubmission
    ) -> OpportunitySubmission:
        """Insert a pending submission."""
        row = OpportunitySubmissionRow(
            id=submission.id,
            target_id=submission.target_id,
            payload=submission.payload,
            note=submission.note,
            status="pending",
            submitted_by=submission.submitted_by,
            submitter_role=submission.submitter_role,
        )
        self._s.add(row)
        await self._s.flush()
        await self._s.refresh(row)
        return _sub(row)

    async def get_submission(self, submission_id: UUID) -> OpportunitySubmission | None:
        """One submission."""
        row = await self._s.get(OpportunitySubmissionRow, submission_id)
        return _sub(row) if row else None

    async def list_submissions(
        self, *, status: str | None, submitted_by: UUID | None
    ) -> list[OpportunitySubmission]:
        """Submissions, newest first."""
        q = select(OpportunitySubmissionRow).order_by(
            OpportunitySubmissionRow.created_at.desc()
        )
        if status is not None:
            q = q.where(OpportunitySubmissionRow.status == status)
        if submitted_by is not None:
            q = q.where(OpportunitySubmissionRow.submitted_by == submitted_by)
        return [_sub(r) for r in await self._s.scalars(q.limit(500))]

    async def save_review(
        self, submission: OpportunitySubmission, *, expected_lock: int
    ) -> OpportunitySubmission:
        """Write the review; conflict if the lock moved or it is not pending."""
        tbl = OpportunitySubmissionRow
        result = await self._s.execute(
            update(tbl)
            .where(
                tbl.id == submission.id,
                tbl.lock_version == expected_lock,
                tbl.status == "pending",
            )
            .values(
                status=submission.status,
                reviewed_by=submission.reviewed_by,
                reviewed_at=submission.reviewed_at,
                reason=submission.reason,
                applied_id=submission.applied_id,
                lock_version=tbl.lock_version + 1,
            )
            .returning(tbl)
            .execution_options(synchronize_session=False)
        )
        row = result.scalar_one_or_none()
        if row is None:
            raise AdmissionConflictError()
        await self._s.refresh(row)
        return _sub(row)

    async def item_link(self, item_id: UUID) -> ItemOpportunityLink | None:
        """The opportunity link of an activity."""
        row = await self._s.get(ItemOpportunityLinkRow, item_id)
        if row is None:
            return None
        return ItemOpportunityLink(row.item_id, row.submission_id, row.opportunity_id)

    async def save_item_link(self, link: ItemOpportunityLink) -> None:
        """Insert or replace the link of an activity."""
        tbl = ItemOpportunityLinkRow
        ins = insert(tbl).values(
            item_id=link.item_id,
            submission_id=link.submission_id,
            opportunity_id=link.opportunity_id,
        )
        await self._s.execute(
            ins.on_conflict_do_update(
                index_elements=[tbl.item_id],
                set_={
                    "submission_id": ins.excluded.submission_id,
                    "opportunity_id": ins.excluded.opportunity_id,
                    "updated_at": dt.datetime.now(dt.UTC),
                },
            )
        )

    async def delete_item_link(self, item_id: UUID) -> bool:
        """Remove the link of an activity; return whether it existed."""
        tbl = ItemOpportunityLinkRow
        result = await self._s.execute(
            delete(tbl).where(tbl.item_id == item_id).returning(tbl.item_id)
        )
        return result.scalar_one_or_none() is not None

    async def resolve_item_links(
        self, submission_id: UUID, opportunity_id: UUID
    ) -> int:
        """Point every activity linked to the submission at the approved entry."""
        tbl = ItemOpportunityLinkRow
        result = await self._s.execute(
            update(tbl)
            .where(tbl.submission_id == submission_id)
            .values(opportunity_id=opportunity_id)
            .returning(tbl.item_id)
            .execution_options(synchronize_session=False)
        )
        return len(result.all())

    async def plan(self, student_id: UUID) -> list[PlanEntry]:
        """A student's saved entries."""
        q = (
            select(OpportunityPlanEntryRow)
            .where(OpportunityPlanEntryRow.student_id == student_id)
            .order_by(OpportunityPlanEntryRow.created_at)
        )
        return [_entry(r) for r in await self._s.scalars(q)]

    async def save_plan_entry(self, entry: PlanEntry) -> PlanEntry:
        """Insert or update the entry of (student, opportunity)."""
        tbl = OpportunityPlanEntryRow
        ins = insert(tbl).values(
            id=entry.id,
            student_id=entry.student_id,
            opportunity_id=entry.opportunity_id,
            planned_grade=entry.planned_grade,
            planned_term=entry.planned_term,
            note=entry.note,
        )
        stmt = ins.on_conflict_do_update(
            index_elements=[tbl.student_id, tbl.opportunity_id],
            set_={
                "planned_grade": entry.planned_grade,
                "planned_term": entry.planned_term,
                "note": entry.note,
            },
        ).returning(tbl)
        row = (
            await self._s.execute(stmt, execution_options={"populate_existing": True})
        ).scalar_one()
        return _entry(row)

    async def delete_plan_entry(self, student_id: UUID, opportunity_id: UUID) -> bool:
        """Remove a saved entry; return whether it existed."""
        tbl = OpportunityPlanEntryRow
        result = await self._s.execute(
            delete(tbl)
            .where(tbl.student_id == student_id, tbl.opportunity_id == opportunity_id)
            .returning(tbl.id)
        )
        return result.scalar_one_or_none() is not None

    async def ai_plan(
        self, student_id: UUID
    ) -> tuple[dict[str, Any], dt.datetime] | None:
        """The last generated plan of a student and when it was made."""
        row = await self._s.get(OpportunityAiPlanRow, student_id)
        return (dict(row.plan), row.created_at) if row else None

    async def save_ai_plan(
        self, student_id: UUID, plan: dict[str, Any], at: dt.datetime
    ) -> None:
        """Replace the student's generated plan."""
        tbl = OpportunityAiPlanRow
        stmt = insert(tbl).values(student_id=student_id, plan=plan, created_at=at)
        await self._s.execute(
            stmt.on_conflict_do_update(
                index_elements=[tbl.student_id],
                set_={"plan": plan, "created_at": at},
            )
        )
