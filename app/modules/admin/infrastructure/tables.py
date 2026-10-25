"""Handles of the tables the admin module reads and writes."""

from app.shared.db import models  # noqa: F401  imports every module's ORM package
from app.shared.db.base import Base

from sqlalchemy import Table


def broadcasts_table() -> Table:
    """Return `admin.broadcasts`."""
    return Base.metadata.tables["admin.broadcasts"]


def notifications_table() -> Table:
    """Return `notify.notifications` (read-only: delivery counts per broadcast)."""
    return Base.metadata.tables["notify.notifications"]
