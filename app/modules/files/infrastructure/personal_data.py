"""Personal-data specification of the files module (export and erasure)."""

from app.modules.files.infrastructure.orm.file import File
from app.modules.files.infrastructure.orm.share import FileShareRow
from app.shared.personal_data import (
    ParentLink,
    PersonalTable,
    SqlPersonalData,
    Treatment,
)

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

E, N, R = Treatment.ERASE, Treatment.NULLIFY, Treatment.RETAIN
_ = ParentLink

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(
        FileShareRow, E, owner="user_id", note="erased by files.delete_owner"
    ),
    PersonalTable(File, E, owner="owner_id", note="erased by files.delete_owner"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
