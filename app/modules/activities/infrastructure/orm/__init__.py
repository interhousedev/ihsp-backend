"""ORM models of the activities schema."""

from app.modules.activities.infrastructure.orm.tables import (
    AnnouncementRow,
    ApplicationRow,
    ClubCourseRow,
    ClubProfileRow,
    ClubRow,
    ConsentEventRow,
    DeclarationRow,
    DraftPickRow,
    DraftRoundRow,
    DraftSignupRow,
    EventReportRow,
    EventRow,
    MembershipRow,
    PlannerRow,
    PointsOptOutRow,
    PointsRow,
    PositionRow,
    RatingRow,
    RsvpRow,
    SeatRow,
    TransferRow,
)
from app.shared.db.base import Base as _SharedBase

from sqlalchemy import MetaData, Table

SCHEMA = "activities"


class _ModuleMetadata:
    """The module's tables of the shared metadata, looked up by bare table name."""

    def __init__(self, shared: MetaData) -> None:
        self._shared = shared

    @property
    def tables(self) -> dict[str, Table]:
        """Tables of the `activities` schema keyed by table name."""
        return {t.name: t for t in self._shared.tables.values() if t.schema == SCHEMA}


class Base:
    """Module view of the one declarative base (tables are in shared metadata)."""

    metadata = _ModuleMetadata(_SharedBase.metadata)


__all__ = [
    "AnnouncementRow",
    "ApplicationRow",
    "Base",
    "ClubCourseRow",
    "ClubProfileRow",
    "ClubRow",
    "ConsentEventRow",
    "DeclarationRow",
    "DraftPickRow",
    "DraftRoundRow",
    "DraftSignupRow",
    "EventReportRow",
    "EventRow",
    "MembershipRow",
    "PlannerRow",
    "PointsOptOutRow",
    "PointsRow",
    "PositionRow",
    "RatingRow",
    "RsvpRow",
    "SeatRow",
    "TransferRow",
]
