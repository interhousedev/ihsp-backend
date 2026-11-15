"""Personal-data specification of the feedback module (export and erasure)."""

from app.modules.feedback.infrastructure.orm.feedback_item import FeedbackItemRow
from app.modules.feedback.infrastructure.orm.feedback_response import (
    FeedbackResponseRow,
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
    PersonalTable(FeedbackResponseRow, E, owner="author_id"),
    PersonalTable(FeedbackItemRow, E, owner="reporter_id"),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
