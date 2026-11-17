"""Port: organizations and comments of opportunities."""

from collections.abc import Sequence
from typing import Protocol
from uuid import UUID

from app.modules.admission.domain.opportunity_comments import (
    OppComment,
    OppCommentReport,
)
from app.modules.admission.domain.orgs import Organization


class OrgRepository(Protocol):
    """Organizations."""

    async def list(self) -> list[Organization]:
        """Every organization ordered by name."""
        ...

    async def get(self, org_id: UUID) -> Organization | None:
        """One organization."""
        ...

    async def by_ids(self, org_ids: Sequence[UUID]) -> dict[UUID, Organization]:
        """The organizations that exist among `org_ids`."""
        ...

    async def save(self, org: Organization) -> Organization:
        """Insert or update."""
        ...

    async def delete(self, org_id: UUID) -> None:
        """Delete one organization."""
        ...


class OppCommentRepository(Protocol):
    """Comments under opportunities and their reports."""

    async def add(self, comment: OppComment) -> OppComment:
        """Insert a comment."""
        ...

    async def get(self, comment_id: UUID) -> OppComment | None:
        """One comment in any state."""
        ...

    async def save(self, comment: OppComment) -> OppComment:
        """Write a changed state."""
        ...

    async def list_for(
        self, opportunity_id: UUID, *, include_hidden: bool
    ) -> list[OppComment]:
        """Published comments (plus hidden ones for staff), oldest first."""
        ...

    async def counts(self, opportunity_ids: Sequence[UUID]) -> dict[UUID, int]:
        """Published comments per opportunity."""
        ...

    async def add_report(self, report: OppCommentReport) -> bool:
        """Insert a report; False when the reporter already reported the comment."""
        ...

    async def get_report(self, report_id: UUID) -> OppCommentReport | None:
        """One report."""
        ...

    async def save_report(self, report: OppCommentReport) -> OppCommentReport:
        """Write a changed report."""
        ...

    async def open_reports(self) -> list[OppCommentReport]:
        """The staff queue: open reports, oldest first."""
        ...

    async def reports_of(self, comment_id: UUID) -> list[OppCommentReport]:
        """Open reports of one comment."""
        ...
