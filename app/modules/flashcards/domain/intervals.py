"""Short labels for the answer buttons: "1m", "10m", "1d", "4d", "2mo"."""

from datetime import timedelta

_MINUTE = 60
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_MONTH = 30 * _DAY


def format_interval(delta: timedelta) -> str:
    """Return the label of an interval (rounded down, at least 1 minute)."""
    seconds = int(delta.total_seconds())
    if seconds < _HOUR:
        return f"{max(1, seconds // _MINUTE)}m"
    if seconds < _DAY:
        return f"{seconds // _HOUR}h"
    if seconds < _MONTH:
        return f"{seconds // _DAY}d"
    return f"{seconds // _MONTH}mo"
