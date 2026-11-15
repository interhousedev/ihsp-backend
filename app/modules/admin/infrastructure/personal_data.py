"""Personal-data specification of the admin module (export and erasure)."""

from app.modules.admin.infrastructure.orm.ai_access import AiAccessRow
from app.modules.admin.infrastructure.orm.broadcast import Broadcast
from app.modules.admin.infrastructure.orm.limit_extension import LimitExtensionRow
from app.modules.admin.infrastructure.orm.telegram_bot import TelegramBotMemberRow
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
    PersonalTable(AiAccessRow, E, owner="user_id"),
    PersonalTable(LimitExtensionRow, E, owner="user_id"),
    PersonalTable(
        Broadcast, R, owner="author_id", note="staff announcement authorship"
    ),
    PersonalTable(TelegramBotMemberRow, E, owner="user_id"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
