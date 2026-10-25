"""Filters of the web notification center."""

from enum import StrEnum


class NotificationFilter(StrEnum):
    """All items, activity (everything but broadcasts) or announcements."""

    ALL = "all"
    ACTIVITY = "activity"
    ANNOUNCEMENTS = "announcements"
