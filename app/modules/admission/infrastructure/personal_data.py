"""Personal-data specification of the admission module (export and erasure)."""

from app.modules.admission.infrastructure.orm.access import (
    EntitlementRow,
    OfficerSettingsRow,
    StaffAssignmentRow,
    StaffSavedViewRow,
)
from app.shared.personal_data import PersonalTable, SqlPersonalData, Treatment

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E = Treatment.ERASE

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(
        EntitlementRow,
        E,
        owner="user_id",
        note="admission eligibility of the account; meaningless without it",
    ),
    PersonalTable(
        OfficerSettingsRow,
        E,
        owner="user_id",
        note="the transcript officer's own pickup place",
    ),
    PersonalTable(
        StaffAssignmentRow,
        E,
        owner="user_id",
        note="the account's staff grants end with it; admission audit events stay",
    ),
    PersonalTable(StaffSavedViewRow, E, owner="user_id"),
    PersonalTable(
        CalendarFeedRow,
        E,
        owner="user_id",
        exclude=("token_hash",),
        note="the calendar feed of the account; the token hash is a secret",
    ),
    PersonalTable(
        CalendarReminderRow,
        E,
        owner="user_id",
        export=False,
        note="ledger of reminders already sent; meaningless without the account",
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
