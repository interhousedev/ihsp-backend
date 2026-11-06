"""Date range arguments shared by tools."""

from datetime import date, timedelta

from app.interfaces.mcp.deps import McpDeps
from app.interfaces.mcp.errors import McpInvalidInputError, McpRangeTooLongError
from app.shared.clock import local_today

MAX_RANGE_DAYS = 120


def resolve_range(
    deps: McpDeps,
    date_from: date | None,
    date_to: date | None,
    *,
    default_days: int,
) -> tuple[date, date]:
    """Return a closed range; missing ends default to today and `default_days` days."""
    start = date_from or local_today(deps.clock)
    end = date_to or start + timedelta(days=default_days - 1)
    check_range(start, end)
    return start, end


def check_range(
    start: date | None, end: date | None, *, max_days: int = MAX_RANGE_DAYS
) -> None:
    """Refuse a reversed range or one longer than `max_days`."""
    if start is None or end is None:
        return
    if end < start:
        raise McpInvalidInputError(params={"reason": "date_to is before date_from"})
    if (end - start).days > max_days:
        raise McpRangeTooLongError(params={"max_days": max_days})
