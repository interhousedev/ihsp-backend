"""Personal-data specification of the ai module (export and erasure)."""

from app.modules.ai.infrastructure.orm.chat import Chat
from app.modules.ai.infrastructure.orm.chat_message import ChatMessage
from app.modules.ai.infrastructure.orm.project import Project, ProjectFile
from app.modules.ai.infrastructure.orm.usage_event import UsageEventRow
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
    PersonalTable(ChatMessage, E, parent=ParentLink(Chat, "chat_id", "owner_id")),
    PersonalTable(Chat, E, owner="owner_id"),
    PersonalTable(ProjectFile, E, parent=ParentLink(Project, "project_id", "owner_id")),
    PersonalTable(Project, E, owner="owner_id"),
    PersonalTable(
        UsageEventRow, N, owner="user_id", note="statistics kept without the user"
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
