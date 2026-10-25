"""Port: reports, sanctions, suggestions, queue and upload counts (materials area)."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from app.modules.library.domain.enums import ItemStatus, ReportStatus
from app.modules.library.domain.moderation_entities import (
    BookSuggestion,
    QueueAgeStats,
    Report,
    ReportGroup,
    Sanction,
)


@dataclass(frozen=True, slots=True)
class QueueEntry:
    """An item waiting in a queue and since when."""

    item_id: UUID
    at: datetime


class ModerationRepository(Protocol):
    """Everything the materials area stores beside the items themselves."""

    # - - - Reports - - -

    async def add_report(self, report: Report) -> None:
        """Insert a report (one open report per item, reporter and reason)."""
        ...

    async def has_open_report(
        self, item_id: UUID, reporter_id: UUID, reason: str
    ) -> bool:
        """True when this person already has an open report with this reason."""
        ...

    async def open_reports(self, item_id: UUID) -> list[Report]:
        """Open reports of the item, oldest first."""
        ...

    async def get_report(self, report_id: UUID) -> Report | None:
        """The report or None."""
        ...

    async def close_reports(
        self,
        item_id: UUID,
        status: ReportStatus,
        *,
        handled_by: UUID | None,
        at: datetime,
        action: str,
    ) -> int:
        """Mark every open report of the item `upheld` or `dismissed`; the count."""
        ...

    async def report_times(self, reporter_id: UUID, since: datetime) -> list[datetime]:
        """When the person filed reports since the moment (for the daily limit)."""
        ...

    async def report_groups(self, item_ids: Sequence[UUID]) -> list[ReportGroup]:
        """Open reports of the items grouped by item and reason."""
        ...

    # - - - Sanctions - - -

    async def add_sanction(self, sanction: Sanction) -> None:
        """Insert a warning or an upload ban."""
        ...

    async def list_sanctions(self, user_id: UUID | None = None) -> list[Sanction]:
        """Sanctions, newest first; of one user when given."""
        ...

    async def active_ban(self, user_id: UUID, now: datetime) -> Sanction | None:
        """The upload ban in force at `now`, or None."""
        ...

    # - - - Suggestions - - -

    async def add_suggestion(self, suggestion: BookSuggestion) -> None:
        """Insert a book suggestion."""
        ...

    async def get_suggestion(self, suggestion_id: UUID) -> BookSuggestion | None:
        """The suggestion or None."""
        ...

    async def save_suggestion(self, suggestion: BookSuggestion) -> None:
        """Update the decision, the file and the form of a suggestion."""
        ...

    async def user_suggestions(
        self, user_id: UUID, *, limit: int
    ) -> list[BookSuggestion]:
        """The person's suggestions, newest first."""
        ...

    async def purgeable_suggestions(
        self, *, declined_before: datetime, limit: int
    ) -> list[BookSuggestion]:
        """Suggestions declined long ago that still name a file or a cover."""
        ...

    async def new_suggestions(self, *, limit: int, offset: int) -> list[BookSuggestion]:
        """Suggestions nobody decided yet, oldest first."""
        ...

    # - - - Queue - - -

    async def review_queue(self, *, limit: int, offset: int) -> list[QueueEntry]:
        """Materials in `pending_review`, oldest submission first."""
        ...

    async def report_queue(
        self, *, held: bool, limit: int, offset: int
    ) -> list[QueueEntry]:
        """Items with open reports (`held` items, or published ones), oldest first."""
        ...

    async def rights_candidates(self) -> list[UUID]:
        """Ids of live books whose rights may need a look (checked in Python)."""
        ...

    async def pending_times(self) -> list[QueueEntry]:
        """Every material in `pending_review` with its submission time."""
        ...

    async def pending_positions(self, item_ids: Sequence[UUID]) -> dict[UUID, int]:
        """1-based place in the review queue of those items that are waiting."""
        ...

    async def queue_age_stats(self, now: datetime) -> QueueAgeStats:
        """Length, oldest and average wait of the review queue."""
        ...

    # - - - Uploads of one person - - -

    async def uploads_page(
        self,
        owner_id: UUID,
        *,
        status: ItemStatus | None,
        limit: int,
        after: tuple[datetime, UUID] | None,
    ) -> list[UUID]:
        """Ids of the person's materials, newest first, after a keyset position."""
        ...

    async def upload_times(
        self, user_id: UUID, since: datetime, *, exclude: UUID | None = None
    ) -> list[datetime]:
        """Submission times of the person's materials since the moment."""
        ...

    async def count_uploads(self, user_id: UUID, since: datetime) -> int:
        """How many materials the person submitted since the moment."""
        ...

    async def open_versions(self, item_id: UUID) -> list[UUID]:
        """Unfinished new versions (draft, queued or sent back) of the item."""
        ...

    async def owner_item_ids(
        self, owner_id: UUID, statuses: Sequence[ItemStatus]
    ) -> list[UUID]:
        """Ids of the person's materials in those statuses."""
        ...

    async def delete_draft(self, item_id: UUID) -> None:
        """Remove a never-submitted draft with its details and file rows."""
        ...

    async def purgeable_items(
        self, *, rejected_before: datetime, unpublished_before: datetime, limit: int
    ) -> list[UUID]:
        """Materials that were rejected or unpublished long ago and still hold files."""
        ...
