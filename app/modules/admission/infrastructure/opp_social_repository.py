"""SQL repositories of organizations and opportunity comments."""

from collections.abc import Sequence
from uuid import UUID

from app.modules.admission.domain.opportunity_comments import (
    OppComment,
    OppCommentReport,
)
from app.modules.admission.domain.orgs import Organization
from app.modules.admission.infrastructure.orm.opp_social import (
    OppCommentReportRow,
    OppCommentRow,
    OrgRow,
)

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession


def _org(r: OrgRow) -> Organization:
    return Organization(
        id=r.id,
        name=r.name,
        kind=r.kind,  # type: ignore[arg-type]
        created_at=r.created_at,
        updated_at=r.updated_at,
        logo_url=r.logo_url,
        logo_zoom=r.logo_zoom,
        website=r.website,
        country=r.country,
    )


def _comment(r: OppCommentRow) -> OppComment:
    return OppComment(
        id=r.id,
        opportunity_id=r.opportunity_id,
        author_id=r.author_id,
        body=r.body,
        created_at=r.created_at,
        status=r.status,  # type: ignore[arg-type]
        hidden_by=r.hidden_by,
        hidden_at=r.hidden_at,
        deleted_at=r.deleted_at,
    )


def _report(r: OppCommentReportRow) -> OppCommentReport:
    return OppCommentReport(
        id=r.id,
        comment_id=r.comment_id,
        reporter_id=r.reporter_id,
        reason=r.reason,
        created_at=r.created_at,
        status=r.status,  # type: ignore[arg-type]
        resolved_by=r.resolved_by,
        resolved_at=r.resolved_at,
    )


class SqlOrgRepository:
    """Organizations."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def list(self) -> list[Organization]:
        """Every organization ordered by name."""
        rows = await self._s.scalars(select(OrgRow).order_by(OrgRow.name, OrgRow.id))
        return [_org(r) for r in rows]

    async def get(self, org_id: UUID) -> Organization | None:
        """One organization."""
        row = await self._s.get(OrgRow, org_id)
        return _org(row) if row else None

    async def by_ids(self, org_ids: Sequence[UUID]) -> dict[UUID, Organization]:
        """The organizations that exist among `org_ids`."""
        if not org_ids:
            return {}
        rows = await self._s.scalars(select(OrgRow).where(OrgRow.id.in_(org_ids)))
        return {r.id: _org(r) for r in rows}

    async def save(self, org: Organization) -> Organization:
        """Insert or update."""
        row = await self._s.get(OrgRow, org.id)
        if row is None:
            row = OrgRow(id=org.id)
            self._s.add(row)
        row.name = org.name.strip()
        row.kind = org.kind
        row.logo_url = org.logo_url
        row.logo_zoom = org.logo_zoom
        row.website = org.website
        row.country = org.country
        await self._s.flush()
        await self._s.refresh(row)
        return _org(row)

    async def delete(self, org_id: UUID) -> None:
        """Delete one organization."""
        await self._s.execute(delete(OrgRow).where(OrgRow.id == org_id))


class SqlOppCommentRepository:
    """Comments under opportunities and their reports."""

    def __init__(self, session: AsyncSession) -> None:
        """Bind the session."""
        self._s = session

    async def add(self, comment: OppComment) -> OppComment:
        """Insert a comment."""
        self._s.add(
            OppCommentRow(
                id=comment.id,
                opportunity_id=comment.opportunity_id,
                author_id=comment.author_id,
                body=comment.body,
                status=comment.status,
            )
        )
        await self._s.flush()
        row = await self._s.get(OppCommentRow, comment.id)
        assert row is not None
        await self._s.refresh(row)
        return _comment(row)

    async def get(self, comment_id: UUID) -> OppComment | None:
        """One comment in any state."""
        row = await self._s.get(OppCommentRow, comment_id)
        return _comment(row) if row else None

    async def save(self, comment: OppComment) -> OppComment:
        """Write a changed state."""
        row = await self._s.get(OppCommentRow, comment.id)
        assert row is not None
        row.status = comment.status
        row.hidden_by = comment.hidden_by
        row.hidden_at = comment.hidden_at
        row.deleted_at = comment.deleted_at
        await self._s.flush()
        await self._s.refresh(row)
        return _comment(row)

    async def list_for(
        self, opportunity_id: UUID, *, include_hidden: bool
    ) -> list[OppComment]:
        """Published comments (plus hidden ones for staff), oldest first."""
        shown = ("published", "hidden") if include_hidden else ("published",)
        rows = await self._s.scalars(
            select(OppCommentRow)
            .where(
                OppCommentRow.opportunity_id == opportunity_id,
                OppCommentRow.status.in_(shown),
            )
            .order_by(OppCommentRow.created_at, OppCommentRow.id)
        )
        return [_comment(r) for r in rows]

    async def counts(self, opportunity_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Published comments per opportunity."""
        if not opportunity_ids:
            return {}
        rows = await self._s.execute(
            select(OppCommentRow.opportunity_id, func.count())
            .where(
                OppCommentRow.opportunity_id.in_(opportunity_ids),
                OppCommentRow.status == "published",
            )
            .group_by(OppCommentRow.opportunity_id)
        )
        return {row[0]: row[1] for row in rows}

    async def add_report(self, report: OppCommentReport) -> bool:
        """Insert a report; False when the reporter already reported the comment."""
        result = await self._s.execute(
            insert(OppCommentReportRow)
            .values(
                id=report.id,
                comment_id=report.comment_id,
                reporter_id=report.reporter_id,
                reason=report.reason,
                status=report.status,
            )
            .on_conflict_do_nothing(index_elements=["comment_id", "reporter_id"])
            .returning(OppCommentReportRow.id)
        )
        return result.scalar_one_or_none() is not None

    async def get_report(self, report_id: UUID) -> OppCommentReport | None:
        """One report."""
        row = await self._s.get(OppCommentReportRow, report_id)
        return _report(row) if row else None

    async def save_report(self, report: OppCommentReport) -> OppCommentReport:
        """Write a changed report."""
        row = await self._s.get(OppCommentReportRow, report.id)
        assert row is not None
        row.status = report.status
        row.resolved_by = report.resolved_by
        row.resolved_at = report.resolved_at
        await self._s.flush()
        return _report(row)

    async def open_reports(self) -> list[OppCommentReport]:
        """The staff queue: open reports, oldest first."""
        rows = await self._s.scalars(
            select(OppCommentReportRow)
            .where(OppCommentReportRow.status == "open")
            .order_by(OppCommentReportRow.created_at, OppCommentReportRow.id)
        )
        return [_report(r) for r in rows]

    async def reports_of(self, comment_id: UUID) -> list[OppCommentReport]:
        """Open reports of one comment."""
        rows = await self._s.scalars(
            select(OppCommentReportRow).where(
                OppCommentReportRow.comment_id == comment_id,
                OppCommentReportRow.status == "open",
            )
        )
        return [_report(r) for r in rows]
