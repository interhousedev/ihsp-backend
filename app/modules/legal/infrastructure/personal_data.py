"""Personal-data specification of the legal module (export and erasure)."""

from app.modules.legal.infrastructure.orm.tables import (
    AcceptanceRow,
    PurposeConsentRow,
)
from app.shared.personal_data import PersonalTable, SqlPersonalData, Treatment

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

R = Treatment.RETAIN

SPECS: tuple[PersonalTable, ...] = (
    PersonalTable(
        AcceptanceRow,
        R,
        owner="user_id",
        scrub=("ip", "user_agent"),
        note="proof of consent is kept; the address and device are cleared",
    ),
    PersonalTable(
        PurposeConsentRow,
        R,
        owner="user_id",
        note="proof of the admission consent and its withdrawal is kept",
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
