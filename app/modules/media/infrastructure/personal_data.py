"""Personal-data specification of the media module (export and erasure)."""

from app.modules.media.infrastructure.orm.tables import MediaJobRow
from app.shared.personal_data import (
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E = Treatment.ERASE

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(MediaJobRow, E, owner="owner_id", note="teacher voice-over job"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
