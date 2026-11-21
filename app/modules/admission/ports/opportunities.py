"""Port: the opportunities catalog, its taxonomy, submissions and student plans."""

import datetime as dt
from types import TracebackType
from typing import Any, Protocol, Self
from uuid import UUID

from app.modules.admission.domain.opportunities import (
    ItemOpportunityLink,
    Opportunity,
    OpportunityDraft,
    OpportunitySubmission,
    PlanEntry,
    TaxonomyNode,
)
from app.modules.admission.ports.repositories import AccessRepository


class OpportunityRepository(Protocol):
    """Rows of the opportunities slice."""

    async def taxonomy(self) -> list[TaxonomyNode]:
        """Every node, ordered by level, position and id."""
        ...

    async def get_node(self, node_id: UUID) -> TaxonomyNode | None:
        """One node."""
        ...

    async def save_node(self, node: TaxonomyNode) -> TaxonomyNode:
        """Insert or update a node."""
        ...

    async def delete_node(self, node_id: UUID) -> None:
        """Delete a node and its descendants."""
        ...

    async def node_in_use(self, node_ids: list[UUID]) -> bool:
        """Return whether a published entry refers to one of the subjects."""
        ...

    async def list_published(self) -> list[Opportunity]:
        """Every live entry."""
        ...

    async def get(self, opportunity_id: UUID) -> Opportunity | None:
        """One entry, live or archived."""
        ...

    async def apply(
        self, draft: OpportunityDraft, *, target_id: UUID | None, by: UUID
    ) -> UUID:
        """Create or overwrite an entry from an approved draft."""
        ...

    async def set_archived(self, opportunity_id: UUID, archived: bool) -> None:
        """Hide or show an entry."""
        ...

    async def add_submission(
        self, submission: OpportunitySubmission
    ) -> OpportunitySubmission:
        """Insert a pending submission."""
        ...

    async def get_submission(self, submission_id: UUID) -> OpportunitySubmission | None:
        """One submission."""
        ...

    async def list_submissions(
        self, *, status: str | None, submitted_by: UUID | None
    ) -> list[OpportunitySubmission]:
        """Submissions, newest first."""
        ...

    async def save_review(
        self, submission: OpportunitySubmission, *, expected_lock: int
    ) -> OpportunitySubmission:
        """Write the review; conflict if the lock moved or it is not pending."""
        ...

    async def item_link(self, item_id: UUID) -> ItemOpportunityLink | None:
        """The opportunity link of an activity."""
        ...

    async def save_item_link(self, link: ItemOpportunityLink) -> None:
        """Insert or replace the link of an activity."""
        ...

    async def delete_item_link(self, item_id: UUID) -> bool:
        """Remove the link of an activity; return whether it existed."""
        ...

    async def resolve_item_links(
        self, submission_id: UUID, opportunity_id: UUID
    ) -> int:
        """Point every activity linked to the submission at the approved entry."""
        ...

    async def plan(self, student_id: UUID) -> list[PlanEntry]:
        """A student's saved entries."""
        ...

    async def save_plan_entry(self, entry: PlanEntry) -> PlanEntry:
        """Insert or update the entry of (student, opportunity)."""
        ...

    async def delete_plan_entry(self, student_id: UUID, opportunity_id: UUID) -> bool:
        """Remove a saved entry; return whether it existed."""
        ...

    async def ai_plan(
        self, student_id: UUID
    ) -> tuple[dict[str, Any], dt.datetime] | None:
        """The last generated plan of a student and when it was made."""
        ...

    async def save_ai_plan(
        self, student_id: UUID, plan: dict[str, Any], at: dt.datetime
    ) -> None:
        """Replace the student's generated plan."""
        ...


class OpportunityUnitOfWork(Protocol):
    """The part of the admission unit of work this slice uses."""

    @property
    def opportunities(self) -> OpportunityRepository:
        """Catalog, taxonomy, submissions and plans."""
        ...

    @property
    def access(self) -> AccessRepository:
        """The audit log."""
        ...

    async def __aenter__(self) -> Self:
        """Open the transaction."""
        ...

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Roll back unless committed."""
        ...

    async def commit(self) -> None:
        """Commit the transaction."""
        ...
