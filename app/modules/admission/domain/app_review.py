"""A versioned AI review of a student's whole application."""

import datetime as dt
from dataclasses import dataclass, field
from typing import Any, Final, Literal
from uuid import UUID

ReviewStatus = Literal["queued", "running", "done", "failed"]
SectionStatus = Literal["pending", "running", "done", "failed", "skipped"]
SECTION_KEYS: Final = (
    "profile",
    "activities",
    "alignment",
    "essays",
    "academics",
    "universities",
    "readiness",
)
ACTIVE: Final = frozenset({"queued", "running"})
STALE_AFTER: Final = dt.timedelta(minutes=20)
"""A queued or running review older than this no longer blocks a new one."""


@dataclass(slots=True)
class AppReview:
    """One review version; `sections` and `report` hold the cleaned model output."""

    id: UUID
    student_id: UUID
    version: int
    status: ReviewStatus
    locale: str
    created_by: UUID
    created_at: dt.datetime
    staff_visible: bool = False
    sections: list[dict[str, Any]] = field(default_factory=list)
    report: dict[str, Any] | None = None
    models: list[str] = field(default_factory=list)
    error_code: str | None = None
    started_at: dt.datetime | None = None
    finished_at: dt.datetime | None = None

    def blocks_new(self, now: dt.datetime) -> bool:
        """True while the review is in flight and not stale."""
        return self.status in ACTIVE and now - self.created_at < STALE_AFTER

    def section_states(self) -> list[dict[str, Any]]:
        """Every section in order; unfinished ones are `pending` or `running`."""
        stored = {s["key"]: s for s in self.sections}
        open_status = "running" if self.status == "running" else "pending"
        if self.status in ("done", "failed"):
            return [stored[k] for k in SECTION_KEYS if k in stored]
        return [
            stored.get(k) or {"key": k, "status": open_status} for k in SECTION_KEYS
        ]
