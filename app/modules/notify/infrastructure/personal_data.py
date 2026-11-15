"""Personal-data specification of the notify module (export and erasure)."""

from app.modules.notify.infrastructure.orm.course_broadcast import CourseBroadcast
from app.modules.notify.infrastructure.orm.notification import Notification
from app.modules.notify.infrastructure.orm.push_subscription import PushSubscription
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
    PersonalTable(Notification, E, owner="user_id"),
    PersonalTable(
        PushSubscription,
        E,
        owner="user_id",
        note="devices only",
        exclude=("endpoint", "p256dh", "auth"),
    ),
    PersonalTable(
        CourseBroadcast, R, owner="author_id", note="staff announcement authorship"
    ),
)


def build_personal_data(
    sessionmaker: async_sessionmaker[AsyncSession],
) -> SqlPersonalData:
    """Specs bound to a session factory."""
    return SqlPersonalData(sessionmaker, SPECS)
