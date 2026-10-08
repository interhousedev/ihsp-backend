"""Handle of the notifications table, looked up from the shared metadata."""

import app.modules.notify.infrastructure.orm  # noqa: F401  registers the models
from app.shared.db.base import Base

from sqlalchemy import Table

NOTIFICATIONS_TABLE = "notify.notifications"


def notifications_table() -> Table:
    """Return `notify.notifications` (the ORM package defines it)."""
    return Base.metadata.tables[NOTIFICATIONS_TABLE]
