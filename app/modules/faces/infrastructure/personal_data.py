"""Personal-data specification of the faces module (export and erasure)."""

from app.modules.faces.infrastructure.orm.tables import (
    DeviceCallRow,
    FaceProfileRow,
    PassageRow,
)
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
    PersonalTable(PassageRow, E, owner="user_id", note="gate passages"),
    PersonalTable(DeviceCallRow, N, owner="matched_user_id", note="device statistics"),
    PersonalTable(
        FaceProfileRow,
        E,
        owner="user_id",
        note="metadata exported; embedding never",
        exclude=("embedding",),
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
