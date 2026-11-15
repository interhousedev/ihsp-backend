"""Personal-data specification of the privacy module (export and erasure)."""

from app.modules.privacy.infrastructure.orm.tables import (
    ErasureRequestRow,
    ExportRow,
)
from app.shared.personal_data import PersonalTable, SqlPersonalData, Treatment

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(
        ExportRow,
        Treatment.ERASE,
        owner="user_id",
        export=False,
        note="the archives in object storage are deleted by privacy.erase_owner",
    ),
    PersonalTable(
        ErasureRequestRow,
        Treatment.RETAIN,
        owner="user_id",
        note="record that the lyceum handled the request",
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
