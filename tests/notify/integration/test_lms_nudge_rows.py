"""LMS nudge rows pass the type constraint and dedupe in the real table."""

from app.modules.notify.infrastructure.outbox_writer import write_notifications
from app.modules.notify.infrastructure.tables import notifications_table
from app.shared.ids import new_id
from app.shared.notifications import NotificationDraft, NotificationType

import sqlalchemy as sa
from sqlalchemy.ext.asyncio import AsyncSession


async def test_each_nudge_type_is_stored_once_per_key(db_session: AsyncSession) -> None:
    user = new_id()
    prefix = f"lms_nudge:test:{user}:"
    drafts = [
        NotificationDraft(user, kind, {"n": 1}, f"{prefix}{kind.value}")
        for kind in (
            NotificationType.LMS_REVIEW_DUE,
            NotificationType.LMS_STREAK_AT_RISK,
            NotificationType.LMS_DEADLINE_SOON,
        )
    ]
    await write_notifications(db_session, drafts)
    await write_notifications(db_session, drafts)

    table = notifications_table()
    result = await db_session.execute(
        sa.select(table.c.type).where(table.c.dedupe_key.like(f"{prefix}%"))
    )
    assert sorted(result.scalars()) == [
        "lms_deadline_soon",
        "lms_review_due",
        "lms_streak_at_risk",
    ]
