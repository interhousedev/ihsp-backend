"""Handles of the notify tables, looked up from the shared metadata."""

import app.modules.notify.infrastructure.orm  # noqa: F401  registers the models
from app.shared.db.base import Base

from sqlalchemy import Table

NOTIFICATIONS_TABLE = "notify.notifications"
PUSH_SUBSCRIPTIONS_TABLE = "notify.push_subscriptions"


def notifications_table() -> Table:
    """Return `notify.notifications` (the ORM package defines it)."""
    return Base.metadata.tables[NOTIFICATIONS_TABLE]


def push_subscriptions_table() -> Table:
    """Return `notify.push_subscriptions`."""
    return Base.metadata.tables[PUSH_SUBSCRIPTIONS_TABLE]
