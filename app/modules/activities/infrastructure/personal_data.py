"""Personal-data specification of the activities module (export and erasure)."""

from app.modules.activities.infrastructure.orm import tables as t
from app.shared.personal_data import (
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N = Treatment.ERASE, Treatment.NULLIFY

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(t.MembershipRow, E, owner="user_id", note="club membership"),
    PersonalTable(t.RsvpRow, E, owner="user_id", note="event sign-up"),
    PersonalTable(t.RatingRow, E, owner="user_id", note="rating"),
    PersonalTable(t.DraftSignupRow, E, owner="user_id", note="volunteer sign-up"),
    PersonalTable(t.DraftPickRow, E, owner="user_id", note="volunteer pick"),
    PersonalTable(t.ClubProfileRow, E, owner="user_id", note="club answers"),
    PersonalTable(t.PointsRow, E, owner="user_id", note="points"),
    PersonalTable(t.PointsOptOutRow, E, owner="user_id", note="points opt-out"),
    PersonalTable(t.ApplicationRow, E, owner="user_id", note="team application"),
    PersonalTable(t.SeatRow, E, owner="user_id", note="team seat"),
    PersonalTable(t.ConsentEventRow, E, owner="user_id", note="consent history"),
    PersonalTable(t.MediaRow, N, owner="uploaded_by", note="media stays with the club"),
    PersonalTable(
        t.MediaRow, N, owner="hidden_by", export=False, note="moderator id cleared"
    ),
    PersonalTable(t.MediaReportRow, E, owner="reporter_id", note="media report"),
    PersonalTable(t.MediaBlockRow, E, owner="user_id", note="media upload block"),
    PersonalTable(t.AlbumRow, N, owner="created_by", note="album stays with the club"),
    PersonalTable(t.ClubRow, N, owner="owner_id", note="club stays, owner cleared"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
