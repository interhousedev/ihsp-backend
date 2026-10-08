"""When a partly failed notification is tried again."""

from datetime import datetime, timedelta

RETRY_DELAYS = (timedelta(minutes=1), timedelta(minutes=5), timedelta(minutes=30))
"""Waits before the first, second and third retry."""

LEASE = timedelta(minutes=10)
"""How long a claimed row stays `sending` before another dispatcher may take it."""


def next_retry_at(attempts: int, now: datetime) -> datetime | None:
    """Return when to retry after `attempts` sends, or None when giving up.

    The first send is attempt 1; each of the three retries waits 1, 5 and 30
    minutes. When the third retry has failed the notification is `failed`.
    """
    if attempts < 1 or attempts > len(RETRY_DELAYS):
        return None
    return now + RETRY_DELAYS[attempts - 1]
